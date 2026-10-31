# RPA 2 — fluxo de execução

**Validação e apuração de contestação · HU-05 a HU-11**

---

## O que este robô faz

**Gatilho:** execução em lote, depois da data de corte, quando os arquivos do mês
já foram recebidos pelo RPA 1.

**Entrega:** as tabelas do WebFat atualizadas com o resultado da validação e com
o comparativo por operadora — **aguardando a decisão do analista**.

⚠️ **Este robô termina num ponto de decisão humana.** Ele não contesta nada: diz
*onde há divergência*. Quem decide contestar, e se haverá retenção, é o analista
no WebFat. É isso que o separa do RPA 3.

```
 SFTP do ClickHub                                RPA 1
         │                                          │
         ▼                                          ▼
 ┌──────────────────┐   arquivos _D em   {operadora}/{ano}/{aaaamm}/
 │ 1. EXPECTATIVA   │   {expectativa}/    Detrafs Recebidos/
 │    (2026-08-10)  │   {PASTAS_...}/            │
 └────────┬─────────┘                            │
          └───────────────┬────────────────────-─┘
                          ▼
 ┌──────────────────┐   _BK e _ERRO em disco
 │ 2. VALIDACAO     │   + tbl_rpa_log_detraf_despesa_arquivos
 │    HU-05 a HU-08 │
 └────────┬─────────┘
          │
          ▼
 ┌──────────────────┐   tbl_rpa_log_detraf_despesa_contestacao
 │ 3. BATIMENTO     │   (uma linha por EOT × remuneração × tráfego)
 │    HU-09 a HU-11 │
 └────────┬─────────┘
          │
          ▼
   👤 analista decide no WebFat  →  RPA 3
```

> **A validação daqui virou rede de segurança em 2026-08-06.** O portão passou a
> ser o RPA 1: ele valida o arquivo na captura, e o que reprova **nunca chega**
> à pasta da operadora — vai para a quarentena, com a resposta à operadora saindo
> na mesma execução.
>
> Este robô continua validando, com **a mesma classe** (`ValidadorColunas`, em
> `comum/dominio/`), e continua marcando `_ERRO`. O que ele não faz mais é
> responder e-mail: se fizesse, a operadora receberia dois avisos sobre o mesmo
> arquivo, com dias de diferença.
>
> 🔴 **Um `_ERRO` aqui é uma anomalia.** Ou o portão do RPA 1 falhou, ou alguém
> pôs o arquivo na pasta à mão. Por isso a reprovação é registrada em nível
> `error`, e não `warning`.

---

# Etapa 1 — `expectativa` (2026-08-10)

`CaptacaoExpectativaService.executar`

Baixa do **SFTP do ClickHub** os arquivos `_D` (Detalhado) do período e os põe em
`CAMINHO_EXPECTATIVA_DETRAF`, de onde a etapa 2 vai lê-los.

Até esta data a expectativa chegava por fora do repositório — o diagrama daqui
dizia `← ICT (outra demanda)`, e o checklist de acessos registrava a pasta como
**somente leitura**.

**Cinco pastas remotas, quatro destinos:**

| Remoto | Destino |
|---|---|
| `/interfaces/GERACAO_DETRAF_SMS_ITF` | `Vivo` |
| `/interfaces/GERACAO_DETRAF_VIVO` | `Vivo` |
| `/interfaces/GERACAO_DETRAF_TELEFONICA` | `TLF` |
| `/interfaces/MVNO/NEXTEL/DESMP` | `MVNO` |
| `/interfaces/GERACAO_DETRAF_TRP` | `Detraf TRP` |

⚠️ **`MVNO` e `Detraf TRP` entraram em `PASTAS_EXPECTATIVAS` junto com esta
etapa**, ou seja: passam a ser **lidas** pela validação e pelo batimento. As
linhas delas entram na comparação da HU-10 e podem virar contestação. Enquanto
vierem vazias, o alerta Q21 vai acusá-las a cada execução — é ruído esperado.

**O filtro** (`eh_detalhado_do_periodo`), com as três condições do script de
origem: o período no nome, **sem** `_L_` (esse é o resumido) e o nome terminando
em `_D`. A terceira é mais estrita que o `EXPECTATIVA_SUBSTRING` do `.env`, que é
substring — são filtros de coisas diferentes, e unificá-los afrouxaria este.

**O destino sobrescreve** o que estiver lá. O ClickHub é a fonte de verdade, e
quem decide se o arquivo será reprocessado é o histórico, que compara tamanho e
data.

### Como rodar sem SFTP

```powershell
# não conecta; segue com o que já está na pasta
main.py --etapa expectativa --dry-run

# lê de um diretório local com os mesmos filtros e o mesmo destino
main.py --etapa expectativa --de-pasta Insumos\Expectativa
```

`PERMITIR_DOWNLOAD_SFTP` é o interruptor, desligado por padrão e desarmado pelo
`--dry-run`. Com ele desligado o `paramiko` nem é importado.

O `--de-pasta` aceita as duas formas de origem: um diretório que **espelhe** a
árvore remota (uma subpasta por origem) ou um **plano**, como o
`Insumos/Expectativa/`. No plano, o destino de cada arquivo sai do **nome** dele
(`comum/dominio/expectativa.pasta_por_nome`) — sem isso, o mesmo arquivo casaria
com as cinco origens e seria copiado quatro vezes, três para a pasta errada.

**O que não deve derrubar a etapa:** uma pasta remota indisponível (as outras
continuam), um arquivo que falha (os demais continuam), e zero arquivos
encontrados — que é aviso, não erro: pode ser o período errado, e a validação
segue com o que já estiver em disco.

---

# Etapa 2 — `validacao` (HU-05 a HU-08)

`ValidacaoDetrafsService.executar`

> Os oito passos abaixo **compartilham estado numa passada só** — em especial o
> conjunto `arquivos_invalidos`, que quase todos alimentam. Por isso eles são
> sub-passos documentados e **não** valores de `--etapa`: não são pontos de
> retomada, e separá-los mudaria o resultado.

### 1.1 Varrer os dois lados

**Onde:** `_preparar_arquivos_detrafs` e `_preparar_arquivos_expectativa`

- **Detraf da operadora:** `{operadora}/{ano}/{aaaamm}/Detrafs Recebidos`, pela
  mesma constante que o RPA 1 usa para gravar;
- **Expectativa Vivo:** as pastas de `PASTAS_EXPECTATIVAS`, filtrando pelo nome.

Operadora com pasta mas **sem Detraf no mês** entra na lista de "sem Detraf" — é
o que denuncia quem simplesmente não enviou.

🔴 **Pasta de expectativa vazia ou ausente vira `error` nomeando a pasta**
(decisão Q21). Não aborta — uma pasta vazia pode ser legítima —, mas o efeito de
passar batido é grave: **sem expectativa, a variação dá 100% e a operadora
inteira é contestada indevidamente**.

O histórico anti-reprocessamento filtra o que já passou. **É por isso que a
segunda execução do mesmo mês processa menos** — use
`python resetar_homologacao.py --referencia AAAAMM` para repetir de verdade.

### 1.1.5 Copiar para a área de trabalho — **o insumo não é tocado**

**Onde:** `AreaDeTrabalho.acolher` → `comum/arquivos/area_de_trabalho.py`

Cada arquivo varrido é copiado para `{DIRETORIO_TEMP}/{aaaamm}/{pasta}-{marca}/`,
e **todos** os passos abaixo operam sobre a cópia: o `_RECUSADO.md`, o `_BK`, o
`_ERRO`, a regravação das linhas válidas e a renomeação para `_EXP`. No fim
(passo 1.8) os artefatos são copiados de volta para a pasta de origem.

🔴 **Por que isto existe.** O passo 1.6 regrava o arquivo de expectativa com as
linhas que passaram. Em 2026-08-10, na primeira execução ponta a ponta, o banco
estava com uma coluna fora do lugar, **nenhuma** linha passou, e os quatro
arquivos de expectativa viraram um cabeçalho cada. Em produção esse arquivo é o
da rede — um problema de ambiente destruía o insumo.

⚠️ **A cópia de trabalho não volta**, só o que tem nome diferente dela. Promover
um arquivo homônimo refaria exatamente a sobrescrita. Quem impede o
reprocessamento do original é o histórico, que é indexado pelo caminho do
**insumo** — não pelo da cópia.

A área é **preservada** por mês: é evidência de homologação, e é o estado parcial
que sobra quando a etapa morre no meio. Quem limpa é o `resetar_homologacao.py`.

### 1.8 Entregar em `DIRETORIO_SAIDA_VALIDACAO`

**Onde:** `AreaDeTrabalho.promover` → `estrutura_pastas.caminho_de_saida`

Os artefatos não voltam para a pasta de entrada. Vão para uma árvore própria:

```
{DIRETORIO_SAIDA_VALIDACAO}/{aaaamm}/Operadoras/{operadora}/Detrafs Recebidos/
{DIRETORIO_SAIDA_VALIDACAO}/{aaaamm}/Expectativa/{Vivo|TLF}/
```

As pastas de entrada ficam **só com insumo**. Isso conserta, de lambuja, um
problema do RPA 3: `consolidacao_contestacao.listar_arquivos_detraf` lista todo
arquivo com extensão válida em `Detrafs Recebidos`, sem filtro de sufixo — o
`_BK` e o `_ERRO` deixados ao lado entravam na consolidação e duplicavam linha.

🔴 `Operadoras/` e `Expectativa/` são ramos separados de propósito: quem varre a
raiz trata todo diretório como uma operadora, e sem a divisão a expectativa seria
processada como se fosse uma.

🔴 **Esta pasta é a ENTRADA da etapa 2.** Até 2026-08-10 a validação gravava em
`{operadora}/{ano}/{aaaamm}/Detrafs Recebidos` e o batimento procurava em
`{operadora}/{ano}/{aaaamm}` — ele **nunca achava um Detraf**, e toda contestação
saía com o lado da operadora zerado e variação de -100%, sem um único erro no
log. Os dois lados agora derivam o caminho da **mesma função**, e
`tests/test_estrutura_de_saida.py` trava isso.

### 1.2 Validar o layout — **antes de tudo**

**Onde:** `comum/dominio/layout_detraf.py::validar_layout`

**Por que é o primeiro passo:** um arquivo com layout diferente é lido **por
posição** e produz números sem sentido em silêncio — o código pega o índice 14
achando que é `R$_Bruto` e recebe minutos. Não faz sentido aplicar as demais
regras sobre ele.

A validação é **posicional** e ignora os nomes das colunas (decisão de
2026-07-31: os nomes reais variam por operadora). Mínimo de 15 colunas; extras à
direita são aceitas.

**Quando recusa**, sai um `{nome}_RECUSADO.md` **ao lado do arquivo**, com
posição, esperado, encontrado e duas linhas do conteúdo.

🔴 **A expectativa Vivo atual é recusada.** É a pendência **N3**: a V2 exige a
coluna `R$ Bruto` (¶443) e o arquivo real termina em `VALOR_LIQUIDO`. Contradição
entre documento e realidade — **não é defeito**, e a rejeição é decisão tomada.

### 1.3 Separar os fluxos `_BK` e `LL`

**Onde:** `_validar_fluxo` → `validacao_inicial/limpeza_trafegos.py`

- **`BK` nos dois** — expectativa **e** Detraf da operadora → gera o arquivo `_BK`;
- **`LL` na expectativa** → gera o `_ERRO`;
- **`LL` no Detraf** → **só sinaliza como inválido**, sem gerar arquivo. O
  arquivo é de outra operadora; não cabe a este robô reescrevê-lo.

O `_BK` rodava só na expectativa até 2026-08-10. A HU-06 é explícita — *"vale
tanto para o arquivo da operadora quanto para o de expectativa Vivo"* — e a
assimetria tinha consequência: o mesmo tráfego L→V ficava separado de um lado e
inteiro do outro, e a comparação da etapa 2 passava a somar coisas diferentes sem
nada indicar.

A diferença de tratamento entre `BK` e `LL` no Detraf **não** é inconsistência: o
`_BK` é uma **cópia** (o original continua íntegro), enquanto o `LL` reescreveria
o arquivo da operadora tirando linhas dele.

### 1.4 Descartar o que o filtro da coluna Rel zera

**Onde:** `_verificar_formato_col5`

Se o filtro de linhas de total (`Rel`, índice 5) zera o arquivo inteiro, ele está
fora do padrão — marcado inválido antes das validações caras.

### 1.5 Validar coluna a coluna

**Onde:** `validacao_inicial/validacao_colunas.py::validar_tudo`

EOTs, referência, tráfego, GH, chamadas, minutos, **tarifa contra a tabela
regulada** e o bloco financeiro (12-15).

A tarifa é a mais densa: filtra por GH, região, regra do descritor e vigência de
data, e compara com `tbl_detraf_tarifas`. **Só as remunerações reguladas** têm o
valor validado (decisão Q9); as demais são só formato.

### 1.6 Categorizar e gravar no banco

**Onde:** `separar_arquivos_por_categoria` → `resultado_validacao.preparar_lote`

Os quatro lotes internos viram os **três** valores que a tabela aceita:

| Lote interno | `tipo_registro` | `status` |
|---|---|---|
| `DETRAF_SUCESSO` | `DETRAF` | Validado |
| `DETRAF_ERRO` | `DETRAF` | Não validado |
| `EXPECTATIVA_SUCESSO` | `EXPECTATIVA` | Validado |
| `EXPECTATIVA_ERRO` | `ERRO` | Não validado |

⚠️ `ERRO` é valor **só de expectativa** — por isso um Detraf reprovado continua
sendo `DETRAF`, e o que muda é o `status`. O enum real é fechado
(`enum('DETRAF','EXPECTATIVA','ERRO')`, confirmado em 2026-08-05).

### 1.7 Salvar o histórico

**Onde:** `_salvar_historico_arquivos_processados` → `comum/arquivos/historico.py`

O histórico é a proteção anti-reprocessamento: um arquivo que já passou não volta.

🔴 **Ele compara conteúdo, não só nome** (desde 2026-08-10). A comparação era só
pelo caminho absoluto, e isso quebrava o critério da HU-03 — *"reenvio de arquivo
com o mesmo nome sobrescreve o anterior e inicia novo processamento"*. O RPA 1
sobrescrevia, o caminho continuava o mesmo, o histórico dizia "já processado", e a
**correção enviada pela operadora era ignorada em silêncio**. Agora tamanho e data
de modificação entram na conta; quando um arquivo volta a ser processado, o log
diz por quê.

### 1.8 Renomear os processados

**Onde:** `renomear_arquivos_processados` — evita reprocessamento futuro.

Válidos ganham `_EXP`; reprovados ganham `_ERRO`.

O `_ERRO` continua importando por dois motivos: é o que impede o
reprocessamento (o batimento acha os arquivos por `ARQUIVOS_VALIDADOS`), e é a
**única saída visível** da rede de segurança — sem ele, ela seria silenciosa.

> **Onde foi parar a HU-04.** A notificação da operadora ficava aqui, no passo
> 1.8, e dependia de achar o e-mail de origem no `_rastreamento.json` do RPA 1
> **pelo nome do arquivo** — busca ambígua por construção, já que o arquivo mudava
> de lugar entre os dois robôs e dois anexos de mesmo nome empatavam.
>
> Ela agora é do RPA 1, que resolve o e-mail pelo `entry_id`, sem adivinhar. Ver
> [`../rpa1_captura/FLUXO.md`](../rpa1_captura/FLUXO.md), passo 2.4.

---

# Etapa 3 — `batimento` (HU-09 a HU-11)

`BatimentoDetrafService.executar`

⚠️ **Lê o que a validação registrou.** Rodá-lo sozinho num mês em que a validação
não rodou dá resultado vazio — o robô avisa, e isso não é defeito.

### 2.1 Varrer de novo, e mapear por operadora

**Onde:** `_preparar_arquivos_detrafs`, `_mapear_arquivos_por_operadora`

O Detraf já vem com a operadora pelo nome da pasta; a expectativa precisa ser
mapeada pelo nome do arquivo.

### 2.2 Consolidar cada lado

**Onde:** `criacao_arquivo_contestacao._consolidar_arquivos`

Remove as linhas de total (`Rel == 1`) e concatena os arquivos da operadora.

### 2.3 Enriquecer com tipo de serviço e remuneração

**Onde:** `_enriquecer_com_tipo`

- **tipo de serviço** da EOT credora, do Anexo 5;
- **remuneração**, resolvida pelo **último caractere do descritor** contra
  `tbl_detraf_mapeamento_descritores` — via `comum/dominio/mapa_remuneracao.py`.

🔴 **É a mesma fonte que o RPA 3 usa para ler o sinal do analista**, e tem que
ser. Até 2026-08-06 este robô usava uma regra fixa com outro vocabulário
(`TUCOM` × `TU-COM`), e a chave **só casava em 2 dos 21 descritores** — o RPA 3
não encontrava o sinal e nada era contestado, sem erro nenhum (defeito A4).

Descritor fora do catálogo vira aviso **nomeando o descritor**.

### 2.4 Comparar e persistir (HU-09/HU-10)

**Onde:** `_comparar_e_persistir`

Agrupa os dois lados por **Devedora × tipo de serviço × remuneração × tráfego ×
GH**, soma `Minutos` e `R$_Bruto`, e calcula a diferença e a variação percentual.

🔴 **Valor que não converte para número vira ZERO, com aviso.** A causa comum é
separador de milhar (`1.234,56`), que a V2 não define para estes campos. **Um
valor zerado aqui vira diferença inventada na contestação** — confira o arquivo
antes de aceitar a apuração.

### 2.5 Aplicar a regra de variação (HU-11)

**Onde:** `_aplicar_analise_contestacao` → `comum/dominio/variacao.py`

Contesta quando a variação é **`>= 1%`** e a operadora cobrou **a mais**.
Variação negativa tem destino próprio (retificação, HU-21 — RPA 4).

Também resolve a `modalidade_tarifa` das linhas `VU-M` em GH reduzido, pelo tipo
de serviço da **devedora**.

### 2.6 Gravar a tabela de contestação

`tbl_rpa_log_detraf_despesa_contestacao`, com `carga_agi = "não carregado"` e
`tipo_contestacao` vazio — **é o campo que o analista preenche**.

---

## Rodando cada etapa

```bash
python main.py                                    # as duas, como na agenda
python main.py --etapa validacao --dry-run
python main.py --etapa batimento --referencia 202507
python resetar_homologacao.py --referencia 202507 # para repetir um cenário
```

### Parar entre as etapas para conferir

```bash
python main.py --pausar --dry-run
```

Ao fim de cada etapa abre uma caixa com o que ela produziu, e a execução só
segue no **Continuar**. Há também **Cancelar** (aborta, com código de saída 2) e
**Abrir pasta**.

🔴 Só funciona com `ENV=dev`, em sessão gráfica, e **nunca** em produção — a
caixa espera indefinidamente, e num robô desassistido isso travaria o processo.
Ver [`../../docs/03-checklists/homologacao-guia-de-partida.md`](../../docs/03-checklists/homologacao-guia-de-partida.md).


---

## O que parece defeito e não é

| O que acontece | Por quê |
|---|---|
| Segunda execução processa menos | O histórico anti-reprocessamento. Use o `resetar_homologacao.py` |
| Toda expectativa Vivo recusada | Pendência **N3** — contradição entre a V2 e o arquivo real |
| Nenhum Detraf marcado `_ERRO` | É o esperado: o RPA 1 recusa antes de salvar. Um `_ERRO` aqui é anomalia, e sai em nível `error` |
| Nenhuma operadora foi notificada | Correto desde 2026-08-06 — quem notifica é o RPA 1, na captura |
| `[Q21] Sem expectativa Vivo em [...]` | Pasta vazia ou ausente. **Confira**: sem expectativa a operadora é contestada indevidamente |
| `... valores viraram ZERO` | Separador de milhar no arquivo. Confira antes de aceitar |
| Batimento sem resultado | A validação não rodou para o mês (2.0) |
| `chave sem linha correspondente` | A linha-base é do Épico 3, fora deste projeto (B-D20) |
| Nada foi contestado | A variação não atingiu 1%, ou a operadora cobrou a menos |

---

## Ver também

- [`../../docs/03-checklists/homologacao-rpa1-e-rpa2.md`](../../docs/03-checklists/homologacao-rpa1-e-rpa2.md) — roteiro de homologação
- [`../rpa3_contestacao_agi_ec/FLUXO.md`](../rpa3_contestacao_agi_ec/FLUXO.md) — o que acontece depois da decisão do analista
