#!/usr/bin/env python3
"""Diagnóstico SOMENTE LEITURA dos endpoints do Traderie (linha de comando).

Rode na sua máquina (a conexão com traderie.com precisa estar liberada):

    python diagnose.py --username SEU_USUARIO
    python diagnose.py --user-id 123456 --ask-token

Cada endpoint de leitura é chamado de verdade SEM token e, se você informar um
(variável TRADERIE_AUTH ou --ask-token, que não mostra o que você digita), também
COM token. A tabela mostra o que o servidor respondeu e a política resultante.
Nenhuma ação que altere a conta é executada. O resultado é gravado em
endpoint_auth.json (sem o token) e o painel passa a usá-lo.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

import app as panel
import traderie
from traderie import TraderieClient, TraderieError


def fmt(cell) -> str:
    if not cell:
        return "—"
    extra = f" ({cell['count']})" if cell.get("count") is not None else ""
    return f"{cell['status'] or '--'} {cell['verdict']}{extra}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", default=traderie.DEFAULT_SLUG)
    ap.add_argument("--username")
    ap.add_argument("--user-id", type=int)
    ap.add_argument("--ask-token", action="store_true", help="pede o token sem exibi-lo")
    args = ap.parse_args()

    token = os.environ.get("TRADERIE_AUTH", "")
    if args.ask_token:
        token = getpass.getpass("Authorization (Enter para pular): ")

    client = TraderieClient(args.slug, token)
    uid = args.user_id
    if uid is None:
        if not args.username:
            ap.error("informe --username ou --user-id")
        try:
            uid = client.search_user(args.username)
        except TraderieError as exc:
            print(f"Busca de usuário falhou: {exc}")
            return 1
        if uid is None:
            print("Usuário não encontrado (confira o slug e o nome exato).")
            return 1
        print(f"ID de '{args.username}': {uid}")

    rows = client.diagnose(uid)
    print(f"\n{'endpoint':15} {'sem token':22} {'com token':22} política  observação")
    for r in rows:
        print(f"{r['endpoint']:15} {fmt(r['anon']):22} {fmt(r['token']):22} {r['policy']:9} {r['note']}")
    if not token:
        print("\nSem token não dá para comparar os dados; informe um para confirmar endpoints públicos.")
    panel.save_policy(client)
    print(f"\nPolítica gravada em {panel.POLICY_FILE.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
