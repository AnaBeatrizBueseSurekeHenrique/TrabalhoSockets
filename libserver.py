import selectors
import struct
import io
import json
import sys

# respostas da busca do cliente!
request_translate = {
    "hello": "olá",
    "how": "como",
    "all": "tudo",
    "yes": "sim",
    "no": "não",
    "maybe": "talvez",
    "are": "está",
    "you": "você",
    "I": "eu",
    "am": "estou",
    "fine": "bem",
    "and": "e",
    "all": "todo",
    "call": "chamar",
    "boy": "menino",
    "girl": "menina",
    "book": "livro",
    "car": "carro",
    "chair": "cadeira",
    "children": "crianças",
    "city": "cidade",
    "dog": "cachorro",
    "door": "porta",
    "enemy": "inimigo",
    "end": "fim",
    "enough": "suficient",
    "eat": "comer",
    "father": "pai",
    "friend": "amigo",
    "go": "ir",
    "good": "bom",
    "food": "comida",
    "hear": "ouvir",
    "house": "casa",
    "inside": "dentro",
    "laugh": "rir",
    "man": "homem",
    "woman": "mulher",
    "name": "nome",
    "never": "nunca",
    "new": "novo",
    "next": "próximo",
    "noise": "barulho",
    "often": "frequentemente",
    "pick": "escolher",
    "play": "jogar",
    "room": "comodo",
    "see": "ver",
    "sell": "vender",
    "sister": "irmã",
    "brother": "irmão",
    "sit": "sentar",
    "smile": "sorrir",
    "speak": "falar",
    "then": "então",
    "think": "pensar",
    "walk": "caminhar",
    "water": "água",
    "work": "trabalho",
    "write": "escrever" 
}
#armazena as informacoes necessarias para a troca de mensagens
class Message:
    def __init__(self, selector, socket, addr):
        '''inicializa a mensagem.'''
        #permite verificar a compleção de entrada e saida em mais de uma socket
        #verificando quais sockets tem E/S pronto pra leitura ou escrita
        self.selector = selector
        # receve o objeto de socket, sendo um objeto de selector que associa um objeto de arquivo com seu descritor
        #caso for vazia, é de uma socket de escuta e a conexão será aceita
        self.socket = socket
        #endereço da conexão
        self.addr = addr
        #salva os dados recebidos no buffer até que bytes o suficiente tenham sido lidos até a mensagem completa ter sido lida
        self._recv_buffer = b""
        self._send_buffer = b""
        # header de tamanho fixo
        self._jsonheader_length = None
        #header de json
        self.jsonheader = None
        #conteudo da mensagem
        self.request = None
        #verifica se a mensagem foi criada ou não
        self.response_created = False
        
    def process_events(self, mask):
        if mask & selectors.EVENT_READ:
            self.read()
        if mask & selectors.EVENT_WRITE:
            self.write()
            
    def _set_selector_events_mask(self, modo):
        '''Faz o selector escutar eventos especificos: leitura, escrita, e leitura e escrita.'''
        if modo == 'r':
            events = selectors.EVENT_READ
        else:
            if modo == "w":
                events = selectors.EVENT_WRITE
            else:   
                if modo == "rw":
                    events = selectors.EVENT_READ | selectors.EVENT_WRITE
        self.selector.modify(self.socket, events, data=self)
    
    def readBytes(self):
        '''faz a leitura da mensagem no socket.recv e a armazana em um buffer'''
        try:
            #se a mensagem está pronta para a leitura:
            data = self.socket.recv(4096)
        except BlockingIOError:
            #caso o recurso não estiver disponível:
            pass
        else:
            if data:
                self._recv_buffer += data
            else:
                raise RuntimeError("O peer está fechado!")    
            
    def writeBytes(self):
        if self._send_buffer:
            print(f"Enviando {self._send_buffer!r} a {self.addr}")
            try:
                # se está pronto para escrever:
                sent = self.socket.send(self._send_buffer)
            except BlockingIOError:
                #se está indisponivel
                pass
            else:  
                self._send_buffer = self._send_buffer[sent:]
                #fecha quando o buffer tiver finalizado, e a mensagem foi enviada.
                if sent and not self._send_buffer:
                    self.close()
    def read(self): 
        '''Verica se bytes suficientes foram lidos no buffer de recebimento, se foram ,os processam, 
        os removem do buffer e escreve o output na variavel'''
        self.readBytes()
        
        if self._jsonheader_length is None:
            self.process_protoheader()
            
        if self._jsonheader_length is not None:
            if self.jsonheader is None:
                self.process_jsonheader()
                
        if self.jsonheader:
            if self.request is None:
                self.process_request()     
   
    def _json_decode(self, json_bytes, encoding):
        '''Decodifica e desserializa o cabeçalho do Json em um diciionario'''
        tiow = io.TextIOWrapper(
            io.BytesIO(json_bytes), encoding=encoding, newline=""
        )
        obj = json.load(tiow)
        tiow.close
        return obj
    
    def _json_encode(self, obj, encoding):
        return json.dumps(obj, ensure_ascii=False).encode(encoding)
    
    def create_response_json_content(self):
        action = self.request.get("action")
        if action == "traduzir":
            query = self.request.get("value")
            resposta = request_translate.get(query) or f"Não há tradução para '{query}'."
            content = {"result": resposta}
        else:
            content = {"result": f"erro! Ação inválida '{action}'."}
        response = {
            "content_bytes": self._json_encode(content, "utf-8"),
            "content_type": "text/json",
            "content_encoding": "utf-8",
        }
        return response
    
    def _create_message(self, *, content_bytes, content_type, content_encoding):
        jsonheader = {
            "byteorder": sys.byteorder,
            "content-type": content_type,
            "content-encoding": content_encoding,
            "content-length": len(content_bytes)
        }
        jsonheader_bytes = self._json_encode(jsonheader, "utf-8")
        message_header = struct.pack(">H", len(jsonheader_bytes))
        message = message_header + jsonheader_bytes + content_bytes
        return message
    
    def process_protoheader(self):
        '''Retorna o tamanho fixo do header'''
        #2 é o tamanho minimo de bytes que o servidor precisa ter lido
        if len(self._recv_buffer) >= 2:
            #lê o valor, o decodifica, e o armazena, e o tira do buffer
                self._jsonheader_length = struct.unpack(
                    ">H", self._recv_buffer[:2]
                )[0]
                self._recv_buffer = self._recv_buffer[2:]
   
    def process_jsonheader(self):
        hdrlength = self._jsonheader_length
        if len(self._recv_buffer) >= hdrlength:
            self.jsonheader = self._json_decode(
                self._recv_buffer[:hdrlength], "utf-8"
            )
            self._recv_buffer = self._recv_buffer[hdrlength:]
            # verifica se todos os valores estão no cabeçalho
            for reqhdr in(
                "byteorder",
                "content-length",
                "content-type",
                "content-encoding",
            ):
                if reqhdr not in self.jsonheader:
                    raise ValueError(f"O Cabeçalho necessário '{reqhdr}' está faltando!")
    
   
    def write(self):
        if self.request:
            if not self.response_created:
                self.create_response()
        self.writeBytes()
    
    def process_request(self): 
        '''Processa o conteudo da mensagem'''
        contentlength = self.jsonheader["content-length"]
        if not len(self._recv_buffer) >= contentlength:
            return
        data = self._recv_buffer[:contentlength]
        self._recv_buffer = self._recv_buffer[contentlength:]
        if self.jsonheader["content-type"]  == "text/json":
            encoding = self.jsonheader["content-encoding"]
            self.request = self._json_decode(data, encoding)
            print(f"Request recebido {self.request!r} de {self.addr}!!")
            self._set_selector_events_mask("w")
        
    def create_response(self):
        if self.jsonheader["content-type"] == "text/json":
            response = self.create_response_json_content()
        message = self._create_message(**response)
        self.response_created = True
        self._send_buffer += message
        
    
    def close(self):
        print(f"Fechando a conexão com {self.addr}")
        try:
            self.selector.unregister(self.socket)
        except Exception as e:
            print(f"Erro: exceção à f'{self.addr}: '{e!r}")    
        try:
            self.socket.close()
        except OSError as e:
            print(f"Erro! exceção de socket.close() para {self.addr} : {e!r}")
        finally:
            self.socket = None
    