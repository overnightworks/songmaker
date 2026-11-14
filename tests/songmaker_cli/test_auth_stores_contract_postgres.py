"""songmaker's session and account stores keep every duty webauth's store contract checks."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker
from webauth.store_contract import STORE_CHECKS, StoreAdapter, StoreCheck

from songmaker_cli.auth_stores import DatabaseSignInTransaction


def _sign_in_transaction_on(url: URL) -> DatabaseSignInTransaction:
    return DatabaseSignInTransaction(sessionmaker(bind=create_engine(url), expire_on_commit=False))


@dataclass(frozen=True)
class _SignInTransactionOnTheSameDatabase:
    """Picklable, so the contract's second process builds its own transaction from the URL."""

    url: URL

    def __call__(self) -> DatabaseSignInTransaction:
        return _sign_in_transaction_on(self.url)


@dataclass(frozen=True)
class _StoreInItsOwnTransaction:
    """Runs each call of one store inside its own sign-in entry, as webauth does."""

    transaction: DatabaseSignInTransaction
    store_of: str

    def __getattr__(self, method: str):
        def call_in_its_own_transaction(*arguments, **keywords):
            with self.transaction() as stores:
                return getattr(getattr(stores, self.store_of), method)(*arguments, **keywords)

        return call_in_its_own_transaction


@pytest.mark.parametrize("check", STORE_CHECKS, ids=lambda check: check.name)
def test_the_stores_keep_the_duty_of_the_webauth_store_contract(
    check: StoreCheck, postgresql_url: URL,
) -> None:
    """The worker database's reset after the case removes the rows the check leaves."""
    transaction = _sign_in_transaction_on(postgresql_url)
    try:
        check.run(
            StoreAdapter(
                accounts=_StoreInItsOwnTransaction(transaction, "accounts"),
                sessions=_StoreInItsOwnTransaction(transaction, "sessions"),
                transaction=transaction,
                transaction_in_another_process=_SignInTransactionOnTheSameDatabase(postgresql_url),
            )
        )
    finally:
        transaction.factory.kw["bind"].dispose()
