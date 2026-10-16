# Databricks notebook source
# MAGIC %md
# MAGIC # ML · Treino, backtest walk-forward e ranking atual
# MAGIC Pergunta: *esta ação vai render mais do que a mediana das ações líquidas nos próximos 21 pregões?*
# MAGIC
# MAGIC 1. **Walk-forward**: para cada mês de teste, treina só com meses cujo alvo já era conhecido (com um mês de
# MAGIC    intervalo) e pontua as ações desse mês. Três modelos: referência de momentum (sem ML), regressão logística e
# MAGIC    gradient boosting (`HistGradientBoostingClassifier`).
# MAGIC 2. **Backtest**: carteira igual-ponderada das 10 maiores pontuações, mensal, com custos de transação, contra o
# MAGIC    universo e o BOVA11. Métricas: AUC, IC (Spearman), retorno acumulado, drawdown.
# MAGIC 3. **Modelo final**: treinado com todos os meses rotulados, regista-se no MLflow (Unity Catalog) e pontua a
# MAGIC    data mais recente (`gold.ml_ranking_atual`).
# MAGIC
# MAGIC Projeto de estudo: não é recomendação de investimento.

# COMMAND ----------

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd().parents[1]))

from src.common import notebook

notebook.declarar(dbutils)
p = notebook.ler(dbutils)
print(p)

# COMMAND ----------

import json

import mlflow
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.audit import control
from src.ml import avaliacao as av
from src.ml.features import FEATURES_ACAO, FEATURES_MACRO

print(f"scikit-learn {sklearn.__version__}, mlflow {mlflow.__version__}")
k = p.catalogo
SEMENTE = 42
TOP_N = 10
e = control.Execucao(k, p.run_id, "ml_treino", "ml", "ml_treino", "gold", p.run_mode)
control.iniciar(spark, e)

# COMMAND ----------

df = spark.table(f"{k}.gold.ml_features").toPandas()
df["data_ref"] = pd.to_datetime(df["data_ref"])
df["alvo"] = av.alvo(df)
RANKS = [f"r_{c}" for c in FEATURES_ACAO]
df[RANKS] = av.ranks_por_data(df, FEATURES_ACAO).to_numpy()
setores = sorted(df["setor"].fillna("Não informado").unique())
df["setor_cod"] = df["setor"].fillna("Não informado").map({s: i for i, s in enumerate(setores)}).astype(int)
X_COLS = RANKS + FEATURES_MACRO + ["setor_cod"]

rotulado = df[df["alvo"].notna()]
datas = sorted(rotulado["data_ref"].unique())
ultima = df["data_ref"].max()
print(f"{len(df)} linhas, {df['ticker'].nunique()} ações, {len(datas)} meses com alvo "
      f"({pd.Timestamp(datas[0]):%Y-%m} a {pd.Timestamp(datas[-1]):%Y-%m}); data mais recente {ultima:%Y-%m-%d}")


def novo_modelo(nome: str):
    if nome == "logistica":
        return make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=2000))
    if nome == "gbm":
        return HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=100, l2_regularization=1.0,
            categorical_features=[X_COLS.index("setor_cod")], random_state=SEMENTE)
    raise ValueError(nome)


def preparar(x: pd.DataFrame, nome: str) -> pd.DataFrame:
    x = x[X_COLS].copy()
    if nome == "logistica":      # sem valores em falta: percentil neutro (0,5) e macro pela mediana
        x[RANKS] = x[RANKS].fillna(0.5)
        x[FEATURES_MACRO] = x[FEATURES_MACRO].fillna(x[FEATURES_MACRO].median())
        x = x.drop(columns=["setor_cod"])
    return x


def pontuar(nome: str, treino: pd.DataFrame, teste: pd.DataFrame):
    if nome == "momentum":       # referência sem ML: quem mais subiu em 12 meses (excluindo o último)
        return teste["r_mom_12_1"].fillna(0.5).to_numpy(), None
    m = novo_modelo(nome).fit(preparar(treino, nome), treino["alvo"].astype(int))
    return m.predict_proba(preparar(teste, nome))[:, 1], m

# COMMAND ----------

# MAGIC %md ## 1-2. Walk-forward e backtest

# COMMAND ----------

bova = spark.sql(f"""
    SELECT data_pregao AS data_ref, lead(preco_ajustado, 21) OVER (ORDER BY data_pregao) / preco_ajustado - 1 AS ret_bova11
    FROM {k}.gold.fct_cotacao_diaria WHERE ticker = 'BOVA11'""").toPandas()
bova["data_ref"] = pd.to_datetime(bova["data_ref"])

MODELOS = ["momentum", "logistica", "gbm"]
experimento = f"/Shared/findata_{p.env}/ml_ranking_acoes"
mlflow.set_experiment(experimento)
previsoes, mensais, resumos = [], [], []
try:
    with mlflow.start_run(run_name=f"walk-forward {p.run_id}") as pai:
        mlflow.log_params({"top_n": TOP_N, "horizonte_pregoes": 21, "universo": "ações, volume >= R$ 1 mi/dia",
                           "intervalo_meses": 1, "minimo_treino_meses": 18, "custo_por_lado": av.CUSTO_POR_LADO,
                           "features": json.dumps(X_COLS), "linhas": len(df)})
        for nome in MODELOS:
            with mlflow.start_run(run_name=nome, nested=True):
                for dobra in av.dobras(datas, minimo_treino=18, intervalo=1):
                    treino = rotulado[rotulado["data_ref"].isin(dobra.treino)]
                    teste = rotulado[rotulado["data_ref"] == dobra.teste]
                    score, _ = pontuar(nome, treino, teste)
                    previsoes.append(teste[["data_ref", "ticker", "ret_fwd", "alvo"]].assign(modelo=nome, score=score))
                prev = pd.concat([x for x in previsoes if x["modelo"].iat[0] == nome])
                mensal = av.carteira_mensal(prev, n=TOP_N).merge(bova, on="data_ref", how="left").assign(modelo=nome)
                r = av.resumo(mensal, mensal["ret_bova11"].dropna())
                mlflow.log_metrics({k_: v for k_, v in r.items() if np.isfinite(v)})
                mlflow.log_text(mensal.to_csv(index=False), "backtest_mensal.csv")
                mensais.append(mensal)
                resumos.append({"modelo": nome, **r})
                print(f"{nome:10s} AUC {r['auc_media']:.3f}  IC {r['ic_medio']:+.3f} (t={r['ic_t']:.2f})  "
                      f"carteira {r['ret_carteira_acum']:+.1%}  universo {r['ret_universo_acum']:+.1%}  "
                      f"BOVA11 {r.get('ret_referencia_acum', float('nan')):+.1%}  meses {r['meses']:.0f}")

        # 3. Modelo final, importância das variáveis e ranking atual
        final_treino = rotulado[rotulado["data_ref"].isin(datas[:-1])]   # último mês rotulado fica de fora (intervalo)
        modelo = novo_modelo("gbm").fit(preparar(final_treino, "gbm"), final_treino["alvo"].astype(int))
        # importância fora da amostra: modelo treinado até 13 meses antes, avaliado nos últimos 12 meses rotulados
        corte = datas[-13]
        m_imp = novo_modelo("gbm").fit(preparar(rotulado[rotulado["data_ref"] < corte], "gbm"),
                                       rotulado.loc[rotulado["data_ref"] < corte, "alvo"].astype(int))
        aval = rotulado[rotulado["data_ref"] >= corte]
        imp = permutation_importance(m_imp, preparar(aval, "gbm"), aval["alvo"].astype(int), scoring="roc_auc",
                                     n_repeats=10, random_state=SEMENTE)
        importancia = pd.DataFrame({"variavel": X_COLS, "importancia": imp.importances_mean,
                                    "desvio": imp.importances_std}).sort_values("importancia", ascending=False)
        mlflow.log_text(importancia.to_csv(index=False), "importancia_permutacao.csv")

        atual = df[df["data_ref"] == ultima].copy()
        atual["score"] = modelo.predict_proba(preparar(atual, "gbm"))[:, 1]
        atual["posicao"] = atual["score"].rank(ascending=False, method="first").astype(int)
        mlflow.set_registry_uri("databricks-uc")
        nome_registo = f"{k}.gold.ranking_acoes"
        info = mlflow.sklearn.log_model(modelo, "modelo", input_example=preparar(atual, "gbm").head(5),
                                        registered_model_name=nome_registo)
        versao_modelo = getattr(info, "registered_model_version", None)
        mlflow.log_param("modelo_registado", f"{nome_registo} v{versao_modelo}")
        e.parameters.update({"mlflow_run": pai.info.run_id, "experimento": experimento,
                             "modelo": f"{nome_registo} v{versao_modelo}",
                             "resumo": {r_["modelo"]: {"auc": round(r_["auc_media"], 4), "ic": round(r_["ic_medio"], 4)}
                                        for r_ in resumos}})
except Exception as ex:
    control.falhar(spark, e, ex)
    raise

# COMMAND ----------

# MAGIC %md ## 4. Tabelas gold do modelo

# COMMAND ----------

def gravar(pdf: pd.DataFrame, nome: str, comentario: str) -> int:
    tabela = f"{k}.gold.{nome}"
    (spark.createDataFrame(pdf).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(tabela))
    spark.sql(f"COMMENT ON TABLE {tabela} IS '{comentario}'")
    return len(pdf)


try:
    c = control.Contagens()
    todas = pd.concat(previsoes)
    c.inserted += gravar(todas.assign(data_ref=todas["data_ref"].dt.date, alvo=todas["alvo"].astype(int)),
                         "ml_previsoes", "Modelo de ranking: pontuações fora da amostra (walk-forward) por modelo, mês e ação")
    m = pd.concat(mensais)
    c.inserted += gravar(m.assign(data_ref=m["data_ref"].dt.date), "ml_backtest_mensal",
                         "Modelo de ranking: carteira top 10 vs universo vs BOVA11 por mês, com custos, AUC e IC")
    c.inserted += gravar(pd.DataFrame(resumos).assign(calculado_em=pd.Timestamp.now(tz="UTC").isoformat(),
                                                      mlflow_run=pai.info.run_id),
                         "ml_resumo", "Modelo de ranking: métricas agregadas do backtest por modelo")
    c.inserted += gravar(importancia, "ml_importancia",
                         "Modelo de ranking: importância das variáveis por permutação (AUC), últimos 12 meses fora da amostra")
    cols = ["ticker", "setor", "score", "posicao"] + FEATURES_ACAO
    c.inserted += gravar(atual[cols].assign(data_ref=ultima.date(), modelo=f"{nome_registo} v{versao_modelo}")
                         .sort_values("posicao"), "ml_ranking_atual",
                         "Modelo de ranking: pontuação das ações na data mais recente (experimental, não é recomendação)")
    control.concluir(spark, e, c)
except Exception as ex:
    control.falhar(spark, e, ex)
    raise

display(pd.DataFrame(resumos))
