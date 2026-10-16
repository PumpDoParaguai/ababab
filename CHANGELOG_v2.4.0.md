# v2.4.0 — Intervalo livre e detalhes dos itens recebidos

- Campo numérico de intervalo, sem horários predefinidos. Aceita minutos inteiros entre 1 e 525600 (365 dias); mantém 60 segundos entre publicações da fila.
- Cada item oferecido preserva imagem, identificação interna, variante, espécie/slot, traits e mutações da instância ofertada.
- Atributos do seu anúncio aparecem separados dos itens recebidos, evitando atribuir características do vendedor ao item do comprador.
- Ofertas com mais de um item ou alternativas mantêm as características de cada item e os grupos de troca.
- Busca de arte no catálogo quando a oferta traz o ID, mas não a imagem. Características ausentes são indicadas, sem presumir que a criatura seja espécie ou slot.
- Revisão da oferta considera mudanças nas características, impedindo aceitar uma versão modificada sem revisá-la.

Validação offline e em Chromium, com API simulada. A consulta autenticada real permanece sem validação nesta revisão.
