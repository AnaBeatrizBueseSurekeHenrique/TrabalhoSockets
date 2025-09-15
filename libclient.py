import io
import json
import selectors
import struct
import sys


class Message:
    def __init__(self, selector, sock, addr, request):
        self.selector = selector
        self.sock = sock
        self.addr = addr
        self.request = request
        self._recv_buffer = b""
        self._send_buffer = b""
        self._request_queued = False
        self._jsonheader_len = None
        self.jsonheader = None
        self.response = None
    
    def process_events(self, mask):
        if mask & selectors.EVENT_READ:
            self.read()
        if mask & selectors.EVENT_WRITE:
            self.write()

    def _set_selector_events_mask(self, modo):
        '''Faz o selector escutar eventos especificos: leitura, escrita, e leitura e escrita.'''
        if modo == "r":
            events = selectors.EVENT_READ
        elif modo == "w":
            events = selectors.EVENT_WRITE
        elif modo == "rw":
            events = selectors.EVENT_READ | selectors.EVENT_WRITE
        self.selector.modify(self.sock, events, data=self)

    def readBytes(self):
        '''faz a leitura da mensagem no socket.recv e a armazana em um buffer'''
        try:
            #se a mensagem está pronta para a leitura:
            data = self.sock.recv(4096)
        except BlockingIOError:
            #caso o recurso não estiver disponível:
            pass
        else:
            if data:
                self._recv_buffer += data
            else:
                raise RuntimeError("Peer está fechado.")

    def writeBytes(self):
        if self._send_buffer:
            print(f"Enviando {self._send_buffer!r} a {self.addr}")
            try:
                # se está pronto para escrever:
                #encia dados a socket
                sent = self.sock.send(self._send_buffer)
            except BlockingIOError:
                #se está indisponivel
                pass
            else:
                self._send_buffer = self._send_buffer[sent:]

    def _json_encode(self, obj, encoding):
        return json.dumps(obj, ensure_ascii=False).encode(encoding)

    def _json_decode(self, json_bytes, encoding):
        '''Decodifica e desserializa o cabeçalho do Json em um diciionario'''
        tiow = io.TextIOWrapper(
            io.BytesIO(json_bytes), encoding=encoding, newline=""
        )
        obj = json.load(tiow)
        tiow.close()
        return obj

    def _create_message(
        self, *, content_bytes, content_type, content_encoding
    ):
        jsonheader = {
            "byteorder": sys.byteorder,
            "content-type": content_type,
            "content-encoding": content_encoding,
            "content-length": len(content_bytes),
        }
        jsonheader_bytes = self._json_encode(jsonheader, "utf-8")
        message_hdr = struct.pack(">H", len(jsonheader_bytes))
        message = message_hdr + jsonheader_bytes + content_bytes
        return message

    def _process_response_json_content(self):
        content = self.response
        result = content.get("result")
        print(f"Tradução obtido: {result}")
    
    def process_response(self):
        content_len = self.jsonheader["content-length"]
        if not len(self._recv_buffer) >= content_len:
            return
        data = self._recv_buffer[:content_len]
        self._recv_buffer = self._recv_buffer[content_len:]
        if self.jsonheader["content-type"] == "text/json":
            encoding = self.jsonheader["content-encoding"]
            self.response = self._json_decode(data, encoding)
            print(f"Tradução recebida {self.response!r} de {self.addr}")
            self._process_response_json_content()
        self.close()
   
    def read(self):
        self.readBytes()

        if self._jsonheader_len is None:
            self.process_protoheader()

        if self._jsonheader_len is not None:
            if self.jsonheader is None:
                self.process_jsonheader()

        if self.jsonheader:
            if self.response is None:
                self.process_response()

    def write(self):
        #verifica se o request está na fila, se não estiver, o adiciona
        if not self._request_queued:
            self.queue_request()

        self.writeBytes()

        if self._request_queued:
            if not self._send_buffer:
                self._set_selector_events_mask("r")

    def close(self):
        print(f"Fechando conexão com {self.addr}")
        try:
            self.selector.unregister(self.sock)
        except Exception as e:
            print(
                f"Erro!"
            )

        try:
            self.sock.close()
        except OSError as e:
            print(f"Erro!")
        finally:
            self.sock = None

    def queue_request(self):
        content = self.request["content"]
        content_type = self.request["type"]
        content_encoding = self.request["encoding"]
        req = {
            "content_bytes": self._json_encode(content, content_encoding),
            "content_type": content_type,
            "content_encoding": content_encoding,
        }
        message = self._create_message(**req)
        self._send_buffer += message
        self._request_queued = True

    def process_protoheader(self):
        '''Retorna o tamanho fixo do header'''
        #2 é o tamanho minimo de bytes que o servidor precisa ter lido
        hdrlen = 2
        if len(self._recv_buffer) >= hdrlen:
            #lê o valor, o decodifica, e o armazena, e o tira do buffer
            self._jsonheader_len = struct.unpack(
                ">H", self._recv_buffer[:hdrlen]
            )[0]
            self._recv_buffer = self._recv_buffer[hdrlen:]

    def process_jsonheader(self):
        hdrlen = self._jsonheader_len
        if len(self._recv_buffer) >= hdrlen:
            self.jsonheader = self._json_decode(
                self._recv_buffer[:hdrlen], "utf-8"
            )
            self._recv_buffer = self._recv_buffer[hdrlen:]
            # verifica se todos os valores estão no cabeçalho
            for reqhdr in (
                "byteorder",
                "content-length",
                "content-type",
                "content-encoding",
            ):
                if reqhdr not in self.jsonheader:
                    raise ValueError(f"O cabeçalho '{reqhdr}' está faltando.")

   