"""Reset an interrupted stage only after the operator stops every backend process."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.db import make_engine
from app.settings import Settings
from app.repository import Repository
from app.errors import AppError


def recover(repo, case_id, stage):
    with repo.transaction() as conn:
        repo._get(conn, 'case', case_id)
        receipt_id = case_id + ':' + stage
        receipt = repo._get(conn, 'stage_run', receipt_id)
        if receipt['status'] != 'running':
            raise AppError('NOT_INTERRUPTED', 'Only running stage receipts may be reset', 409)
        receipt.update(status='failed', error='OPERATOR_RESET')
        repo._put(conn, 'stage_run', receipt_id, receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-id', required=True)
    parser.add_argument('--stage', choices=['plan', 'assess', 'report'], required=True)
    parser.add_argument('--confirm-server-stopped', action='store_true', required=True)
    args = parser.parse_args()
    engine = make_engine(Settings().database_url)
    try:
        recover(Repository(engine), args.case_id, args.stage)
        print('Receipt reset. No quota refunded and no provider called. Restart the server and explicitly retry the stage.')
    except AppError as exc:
        parser.exit(1, exc.code + ': ' + exc.message + '\n')
    finally:
        engine.dispose()


if __name__ == '__main__': main()
