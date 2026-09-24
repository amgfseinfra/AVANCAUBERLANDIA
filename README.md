# Painel Avança Uberlândia

Site que mostra as obras do programa Avança Uberlândia. Os dados vêm do Notion e são atualizados todo dia sozinhos, ou na hora, com um clique.

## O que tem aqui

| Arquivo | Para que serve | Precisa mexer? |
|---|---|---|
| `config.json` | Regras do painel: links das bases, tag, fontes, eixos, total do programa | Sim, quando algo mudar |
| `index.html` | Visual do painel (os dados entram na hora de publicar) | Não |
| `scripts/atualizar_dados.py` | Busca os dados no Notion e monta o site | Não |
| `.github/workflows/atualizar.yml` | Agenda a atualização diária e publica o site | Não |

---

## Primeira vez (cerca de 15 minutos)

### 1. No Notion: liberar o acesso da conexão

1. Na conexão que você criou (app.notion.com/developers/connections), confira se a permissão de **ler conteúdo** está marcada.
2. Abra a página onde ficam as bases das obras e clique em **"..."** (canto superior direito) > **Conexões** > escolha a sua conexão.
   Liberando essa página, todas as bases dentro dela entram junto.

### 2. Conferir os links das bases

No `config.json`, cada base tem um campo `"link_ou_id"`. As três primeiras já estão preenchidas com os códigos que vieram nos nomes dos CSVs exportados.

Se a primeira execução disser que "o Notion não encontrou essa base", troque pelo link:

1. No Notion, passe o mouse sobre a base e clique no ícone de abrir em página inteira.
2. Copie o endereço do navegador.
3. Cole no `"link_ou_id"` daquela base, entre as aspas.

A base de **objetos entregues** já está com o link. Se criar outra base, cole o link dela do mesmo jeito.

### 3. No GitHub: criar o repositório

1. Em github.com, clique em **+** (canto superior direito) > **New repository**.
2. **Repository name**: `painel-avanca` (esse nome entra no endereço do site).
3. Marque **Public** e **Add a README file**.
4. Clique em **Create repository**.

### 4. Guardar o token do Notion

1. No repositório: **Settings** > **Secrets and variables** > **Actions** > **New repository secret**.
2. **Name**: `NOTION_TOKEN`
3. **Secret**: cole o token do Notion.
4. Clique em **Add secret**.

O token fica guardado e escondido. Ele não aparece no site nem nos arquivos.

### 5. Ligar o site (GitHub Pages)

**Settings** > **Pages** > em **Source**, escolha **GitHub Actions**.

### 6. Enviar os arquivos

1. Na página inicial do repositório: **Add file** > **Upload files**.
2. Arraste tudo o que está dentro da pasta `painel-avanca` (arquivos e as pastas `scripts` e `.github`).
3. Clique em **Commit changes**.

Confira se a pasta `.github` apareceu na lista de arquivos. Se não apareceu:
**Add file** > **Create new file** > no nome, digite `.github/workflows/atualizar.yml` > cole o conteúdo desse arquivo (abra-o no Bloco de Notas) > **Commit changes**.

### 7. Primeira publicação

Assim que os arquivos entram, a aba **Actions** mostra "Atualizar painel" rodando (bolinha amarela). Em 1 a 2 minutos:

- **Verde**: o site está no ar. O endereço aparece em **Settings** > **Pages** (algo como `https://seu-usuario.github.io/painel-avanca/`).
- **Vermelho**: clique na execução. O resumo explica, em português, o que ajustar. O site anterior continua no ar.

---

## Dia a dia

- **Atualização automática**: todo dia por volta das 5h (o GitHub às vezes atrasa alguns minutos).
- **Atualizar agora**: clique no botão **Atualizar agora**, no topo do painel. Ele abre o GitHub (é preciso estar logado com acesso ao repositório); lá, clique em **Run workflow** e confirme. O painel recarrega sozinho quando a versão nova estiver no ar, em 1 a 3 minutos.
  Também dá para fazer direto no GitHub: aba **Actions** > **Atualizar painel** > **Run workflow** > **Run workflow**.
- **Alterou o `config.json`**: o site se atualiza sozinho ao salvar.
- O topo do painel mostra a data e a hora da última atualização.

## Como editar o config.json

No GitHub, clique em `config.json` > ícone de lápis > altere > **Commit changes**.

Mexa só nos textos entre aspas e nos números. Se uma vírgula ou aspa sair do lugar, a atualização para e diz a linha do erro, e o site continua como estava.

| Quero... | Onde mexer |
|---|---|
| Mostrar um aviso no topo do painel | `"aviso_no_topo"`: escreva o texto (vazio = sem aviso) |
| Esconder o botão "Atualizar agora" | `"botao_atualizar_agora": false` |
| Mudar o total do programa | `"total_do_programa"` (só números, sem pontos) |
| Mudar o valor previsto de uma fonte | `"fontes"` > `"disponivel"` |
| Fazer uma dotação do Notion contar como fonte oficial | acrescente o nome, escrito como no Notion, em `"nomes_no_notion"` da fonte |
| Criar ou renomear um eixo temático | `"eixos"`: o nome tem que ser igual à opção do Notion (maiúsculas, acentos e vírgulas não fazem diferença) |
| Colocar um aviso em letra pequena embaixo de uma fonte | `"fontes"` > `"nota"` daquela fonte |
| Renomeei uma coluna no Notion | `"bases"` > `"colunas"`: troque pelo nome novo |
| Mostrar todos os objetos de uma base, mesmo sem a tag | `"exigir_tag": false` naquela base |

## O que o painel faz sozinho

- **Tag**: só entram objetos com a tag "Avança Uberlândia" (nas bases com `"exigir_tag": true`).
- **Eixo temático**: usa o campo "Eixo temático" do Notion. Se ele estiver vazio, o eixo é deduzido pelo nome do objeto (regras em `"deducao_de_eixo"`). Se tiver um eixo que não está na lista do `config.json`, o objeto entra em "Outros" e o resumo da atualização avisa.
- **Fontes**: dotações fora da lista oficial aparecem como "Outros"; dotação vazia aparece como "Não informada".
- **Aditivos**: o valor de cada obra é o do contrato original; os aditivos aparecem numa linha própria.
- **Rescisões**: objetos com "rescisão" na situação ficam de fora do painel (lista em `"ignorar_situacao_com"`). O resumo da atualização mostra quais foram.

## Bom saber

- **O site é público**: quem tiver o link vê o painel. Buscadores como o Google são orientados a não listar a página.
- **Se a atualização diária parar**: o GitHub pausa os agendamentos de repositórios públicos depois de 60 dias sem alterações. Na aba **Actions** aparece um aviso; clique em **Enable workflow**.
- **Token trocado ou expirado**: **Settings** > **Secrets and variables** > **Actions** > lápis ao lado de `NOTION_TOKEN` > cole o novo.
