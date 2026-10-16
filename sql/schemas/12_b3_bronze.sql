-- Bronze da B3: COTAHIST (cotações históricas), uma linha por registo 01 do mercado à vista, campos do layout de
-- largura fixa como texto (sem espaços à direita) e preços ainda com as 2 casas decimais implícitas.
-- Criada pelo notebook bronze/b3 se não existir; mantida aqui para o DDL ficar versionado.

CREATE TABLE IF NOT EXISTS ${catalog}.bronze.b3_cotahist (
  tipreg               STRING,
  data_pregao          STRING COMMENT 'AAAAMMDD',
  codbdi               STRING COMMENT 'Código BDI (02 lote padrão, 12 FII, 14 certificados/ETF, ...)',
  codneg               STRING COMMENT 'Código de negociação (ticker)',
  tpmerc               STRING COMMENT 'Tipo de mercado (010 = à vista)',
  nomres               STRING,
  especi               STRING,
  prazot               STRING,
  modref               STRING,
  preabe               STRING,
  premax               STRING,
  premin               STRING,
  premed               STRING,
  preult               STRING,
  preofc               STRING,
  preofv               STRING,
  totneg               STRING,
  quatot               STRING,
  voltot               STRING,
  preexe               STRING,
  indopc               STRING,
  datven               STRING,
  fatcot               STRING,
  ptoexe               STRING,
  codisi               STRING,
  dismes               STRING COMMENT 'Número de distribuição do papel (muda com eventos societários)',
  _source_file_name    STRING,
  _reference_period    STRING COMMENT 'AAAA (ficheiro anual) ou AAAA-MM-DD (diário)',
  _source_system       STRING    NOT NULL,
  _source_entity       STRING    NOT NULL,
  _source_url          STRING    NOT NULL,
  _source_file_path    STRING    NOT NULL,
  _file_hash           STRING    NOT NULL,
  _record_hash         STRING    NOT NULL,
  _ingestion_timestamp TIMESTAMP NOT NULL,
  _pipeline_run_id     STRING    NOT NULL
)
USING DELTA
CLUSTER BY (data_pregao)
COMMENT 'B3 COTAHIST: registos do mercado à vista como recebidos (texto)';
