# v2.3.0 — Chat e contraproposta oficial

- Counter Offer em Shooms dentro da conversa, com confirmação do valor, quantidade e destinatário.
- Contrato `POST /api/creaturesofsonaria/offers` confirmado no cliente público do Traderie: preserva `root_offer`, `parent_offer`, `last_offer` e `parent_user` e valida estoque quando aplicável.
- Chat consulta novas mensagens a cada 5 segundos, preserva rascunho e rolagem e organiza as mensagens cronologicamente.
- Envio de texto inclui o objeto da conversa e reconhece `messageId` na resposta; limite padrão de 500 caracteres, conforme o site.
- Mensagens continuam acessíveis após o encerramento da oferta. Cada leitura/envio verifica o vínculo da conversa com a conta; trocar conta limpa os vínculos da sessão.
- Erros não apagam mensagens ou rascunhos, e escritas não são repetidas automaticamente. Leituras recuam após falhas e respeitam limites informados pelo servidor.
- Interface da conversa adaptada ao celular e navegação por teclado.

Escopo: contrapropostas em Shooms sobre ofertas recebidas; sem seletor de itens ou anexos no chat. Histórico inicial de 50 mensagens. O HTTP 403 nas consultas autenticadas impediu validar envios reais nesta revisão.
