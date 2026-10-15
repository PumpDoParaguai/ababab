# v2.0.0

- Editor refeito com navegação pelo catálogo, busca, seleção e resumo lateral; adaptação para celular e navegação por teclado.
- Tema refeito com superfícies pretas/cinzas neutras e acentos azuis, substituindo a sobreposição de estilos de versões anteriores.
- Removidos modelos, parsers, caches, endpoint e código de interface de preços/cotações.
- Catálogo oficial verificado ao vivo, independente da conta, com filtragem, paginação e propriedades reais.
- Busca protege contra respostas atrasadas e permite tentar novamente após falhas.
- Relógios mostram segundos também em anúncios antigos; sincronização preserva os dados quando a conexão falha.
- Regras de liberação confirmadas no site: 20h/18h/6h/30min conforme perfil; preservação simultânea do sinal e horário da API, tratamento de limites e proteção contra duplicação manual/automática.
- Mantidas as ofertas por anúncio, rotinas, agrupamento e controles de conta; sem aba de negociações.
- Dependências reproduzíveis e testes isolados dos arquivos de configuração do usuário.

Validação: testes locais automatizados e consultas reais de catálogo/paginação/propriedades. Publicações e republicações foram simuladas, sem alterar a conta.
