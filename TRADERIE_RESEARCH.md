# Integração verificada — 15/10/2026

## Catálogo real

A API `GET https://traderie.com/api/creaturesofsonaria/items` respondeu com itens oficiais. Os parâmetros `search`, `type`, `page`, `active=true`, `properties=` e `variants=` correspondem às chamadas observadas no código público do próprio site.

- `type=Creatures`: espécies e slots; 24 itens por página nas consultas realizadas.
- `type=plushies`: plushies.
- `type=palettes`: paletas.
- `id=<item>`: detalhe de um item.
- Resposta: `items`, com `id`, `name`, `type`, `img` e `properties`. Campos de preço são descartados na normalização.
- Exemplo confirmado: Mijusuima, item `1219367524`, tipo `Creatures`; a propriedade `Species or Slot?` tem ID `828` no retorno atual. Não há ID fixo no editor.
- Propriedades booleanas de mutações e traits pertencem a grupos; o limite vem de `format.limit` do grupo. Propriedades não suportadas, como seletor especial de itens para Palette, não são convertidas em tipos inventados.

As páginas HTML do site atualmente podem trazer apenas o carregador da aplicação, sem links de criação. A versão nova usa a API de catálogo diretamente, em vez de extrair números de páginas de preços ou usar anúncios do vendedor.

## Disponibilidade

O código público em `https://traderie.com/assets/index-uqDPzEb-.js`, obtido nesta sessão, contém o cálculo do botão Relist:

1. Permissão `LISTINGS:REFRESH_30_MINUTES`: 30 minutos.
2. Permissão `LISTINGS:REFRESH_6_HOURS`: 6 horas.
3. Usuário com `reviews >= 1000`: 18 horas.
4. Demais contas: 20 horas.

O avaliador de papéis do mesmo arquivo identifica benefícios de 6h em `patron`/`champion` e de 30min em `prime`/`epic`/`investor`/`legendary` e alguns papéis de equipe, respeitando escopo do jogo/site. O programa usa os papéis retornados pelo perfil, não um plano escolhido arbitrariamente na interface. Flags ou horários explícitos retornados pelo servidor continuam prioritários.

Essas regras definem quando tentar. A API ainda pode negar a operação; o cliente só registra sucesso após aceitação. O timestamp é sincronizado novamente com o servidor. Não existe confirmação de um canal de eventos do Traderie para esse fluxo.

## Escritas

As rotas `PUT /listings/refresh`, `POST /listings/create` e `POST /sell` foram herdadas do projeto e comparadas ao código público quando disponíveis. O tipo do item enviado na criação vem do catálogo atual. Publicações, exclusões e republicações não foram enviadas à conta real durante o desenvolvimento.

As leituras públicas de perfil e anúncios da conta de teste responderam; a lista de anúncios estava vazia. O token não foi persistido. Autenticação do token e aceitação de escritas permanecem sem validação ao vivo.

## Limitações

Os testes offline e de navegador cobrem os contratos e casos de falha; não garantem que uma escrita real será aceita. Houve bloqueios de rede/Cloudflare em requisições iniciais, e o acesso funcionou nas consultas finais usando o cliente do projeto. Não há contorno de CAPTCHA ou anti-bot. Imagens do CDN podem falhar e têm fallback visual.

## Preço fixo — contrato recebido em 15/10/2026

O usuário forneceu o payload de `listings/create` para uma publicação de preço fixo no próprio Traderie. Campos específicos: `acceptListingPrice: true`, `makeOffer: false`, `free: false`, `currencyGroupPrices: [{group: 0, nmt: 10000000, currency: true}]`. O tipo é `Creatures`; a propriedade espécie/slot usa o ID retornado pelo catálogo (828 no exemplo). Na API compartilhada, Shooms utiliza a chave `nmt`.

A v2.1.0 preserva esse formato e valida um único valor positivo inteiro. Ao escolher ofertas, omite `currencyGroupPrices` e envia `acceptListingPrice: false`, `makeOffer: true`. Não consulta valores de mercado.

Durante esta revisão, consultas ao Traderie falharam no túnel do proxy com HTTP 403, antes de autenticação ou resposta do site. A autorização do usuário para criar/excluir na conta de teste foi recebida, mas não houve execução dessas escritas reais. Contratos e ciclos foram validados com respostas simuladas; as leituras reais descritas nas seções anteriores são da revisão v2.0.0.

## Notificações e ofertas — v2.2.0

A central reutiliza as rotas herdadas `GET notifications`, `GET offers?accepted=open&seller=<conta>`, `PUT notifications/read`, `PUT offers/accept` e `PUT offers/deny`. A leitura é periódica (15 segundos), sem webhook presumido. O cliente preserva os valores recebidos em `prices`, `currencyGroupPrices` ou `nmt`, sem acrescentar médias de mercado.

O formato da contraproposta nativa ainda não foi confirmado. O usuário foi solicitado a fornecer URL, método e Request Payload da ação Counter Offer. Até lá, o painel abre o anúncio no site oficial para essa operação. A rota antiga de negociação por mensagem permanece distinta da contraproposta formal.

Para ícones, prioriza a URL retornada nos metadados da propriedade. Nomes de arquivos derivados são apenas alternativas; se falharem, usa SVGs locais, sem alegar que sejam os ícones oficiais. A conexão ao site nesta revisão retornou erro 403 do túnel do proxy antes de alcançar o Traderie.
