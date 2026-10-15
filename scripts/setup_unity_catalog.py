"""Cria (ou confirma) os objetos do Unity Catalog de um ambiente, de forma idempotente.

Objetos: storage credential (Access Connector), external locations por contêiner, catálogo, schemas com
localização gerida, volumes externos e permissões por grupo. Não precisa de cluster: usa as APIs REST.

Uso:  python scripts/setup_unity_catalog.py --env dev [--skip-validation]
Autenticação: login do Azure CLI (az login), que tem de ser admin do workspace e do metastore.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from databricks.sdk import WorkspaceClient  # noqa: E402
from databricks.sdk.errors import NotFound, ResourceAlreadyExists  # noqa: E402
from databricks.sdk.service import catalog as uc  # noqa: E402

from src.common.config import carregar_ambiente  # noqa: E402

log = logging.getLogger("setup_uc")


def _url(conta: str, conteiner: str, caminho: str = "") -> str:
    base = f"abfss://{conteiner}@{conta}.dfs.core.windows.net/"
    return base + caminho.strip("/") if caminho else base


def garantir_credencial(w: WorkspaceClient, nome: str, access_connector_id: str) -> None:
    try:
        w.storage_credentials.get(nome)
        log.info("storage credential %s já existe", nome)
    except NotFound:
        w.storage_credentials.create(
            name=nome,
            azure_managed_identity=uc.AzureManagedIdentityRequest(access_connector_id=access_connector_id),
            comment="Access Connector da plataforma (identidade gerida)",
        )
        log.info("storage credential %s criada", nome)


def garantir_external_location(w, nome: str, url: str, credencial: str, skip_validation: bool) -> None:
    try:
        atual = w.external_locations.get(nome)
        if atual.url.rstrip("/") != url.rstrip("/"):
            raise RuntimeError(f"external location {nome} aponta para {atual.url}, esperado {url}")
        log.info("external location %s já existe", nome)
    except NotFound:
        w.external_locations.create(name=nome, url=url, credential_name=credencial, skip_validation=skip_validation)
        log.info("external location %s criada -> %s", nome, url)


def garantir_catalogo(w, nome: str, local: str) -> None:
    try:
        w.catalogs.get(nome)
        log.info("catálogo %s já existe", nome)
    except NotFound:
        w.catalogs.create(name=nome, storage_root=local, comment="Plataforma de dados financeiros (BCB/CVM)")
        log.info("catálogo %s criado", nome)


def garantir_schema(w, catalogo: str, nome: str, local: str, comentario: str) -> None:
    try:
        w.schemas.get(f"{catalogo}.{nome}")
        log.info("schema %s.%s já existe", catalogo, nome)
    except NotFound:
        w.schemas.create(name=nome, catalog_name=catalogo, storage_root=local, comment=comentario)
        log.info("schema %s.%s criado", catalogo, nome)


def garantir_volume(w, catalogo: str, schema: str, nome: str, local: str, comentario: str) -> None:
    try:
        w.volumes.read(f"{catalogo}.{schema}.{nome}")
        log.info("volume %s.%s.%s já existe", catalogo, schema, nome)
    except NotFound:
        w.volumes.create(catalog_name=catalogo, schema_name=schema, name=nome,
                         volume_type=uc.VolumeType.EXTERNAL, storage_location=local, comment=comentario)
        log.info("volume %s.%s.%s criado", catalogo, schema, nome)


def conceder(w, tipo: uc.SecurableType, nome: str, principal: str, privilegios: list[uc.Privilege]) -> None:
    try:
        # A API espera o tipo em minúsculas ("catalog", "schema", "volume").
        w.grants.update(securable_type=tipo.value.lower(), full_name=nome,
                        changes=[uc.PermissionsChange(principal=principal, add=privilegios)])
        log.info("grant %s em %s para %s", [p.value for p in privilegios], nome, principal)
    except Exception as e:  # grupo de conta ainda não criado: não bloqueia o resto da configuração
        log.warning("grant ignorado (%s em %s): %s", principal, nome, e)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="dev")
    ap.add_argument("--skip-validation", action="store_true",
                    help="não validar o acesso ao ADLS (útil antes de aplicar o RBAC do Access Connector)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    cfg = carregar_ambiente(args.env)
    conta = cfg["azure"]["storage_account"]
    ucfg = cfg["unity_catalog"]
    cat = ucfg["catalog"]
    w = WorkspaceClient(host=cfg["databricks"]["host"], auth_type="azure-cli")

    garantir_credencial(w, ucfg["storage_credential"], cfg["azure"]["access_connector_id"])

    conteineres = sorted({s["container"] for s in ucfg["schemas"].values()}
                         | {v["container"] for v in ucfg["volumes"].values()})
    for c in conteineres:
        garantir_external_location(w, f"el_{cat}_{c}", _url(conta, c), ucfg["storage_credential"], args.skip_validation)

    garantir_catalogo(w, cat, ucfg["catalog_location"])
    for nome, s in ucfg["schemas"].items():
        garantir_schema(w, cat, nome, _url(conta, s["container"], s["path"]), s["comment"])
    for nome, v in ucfg["volumes"].items():
        garantir_volume(w, cat, v["schema"], nome, _url(conta, v["container"]), v["comment"])

    # Permissões de menor privilégio: engenharia escreve em todas as camadas; analistas só leem a gold.
    eng, ana = ucfg["groups"]["engineers"], ucfg["groups"]["analysts"]
    P = uc.Privilege
    conceder(w, uc.SecurableType.CATALOG, cat, eng, [P.USE_CATALOG])
    conceder(w, uc.SecurableType.CATALOG, cat, ana, [P.USE_CATALOG])
    for nome in ucfg["schemas"]:
        conceder(w, uc.SecurableType.SCHEMA, f"{cat}.{nome}", eng,
                 [P.USE_SCHEMA, P.SELECT, P.MODIFY, P.CREATE_TABLE, P.CREATE_FUNCTION, P.CREATE_VOLUME])
    conceder(w, uc.SecurableType.SCHEMA, f"{cat}.gold", ana, [P.USE_SCHEMA, P.SELECT])
    for nome, v in ucfg["volumes"].items():
        conceder(w, uc.SecurableType.VOLUME, f"{cat}.{v['schema']}.{nome}", eng, [P.READ_VOLUME, P.WRITE_VOLUME])

    log.info("Unity Catalog do ambiente %s pronto", args.env)


if __name__ == "__main__":
    try:
        main()
    except ResourceAlreadyExists as e:  # corrida entre execuções paralelas
        log.error("objeto criado por outra execução: %s", e)
        sys.exit(1)
