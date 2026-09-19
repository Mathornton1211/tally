"""Who is asking, and therefore what the database is allowed to return.

Every route takes its connection from here instead of reaching into the pool.
The viewer is carried in a ContextVar set by the auth middleware, so no route
signature mentions it and no query has to remember to filter -- `tally_can_see`
in the v_txn view does that once, for everything.

`set_config(..., true)` is transaction-local, so the setting cannot leak to the
next request that borrows the same pooled connection. That property is the
whole reason this is safe, and it is why the pool must not be in autocommit
mode: a local setting outside a transaction silently does nothing.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from .state import state

# None means "nobody in particular is asking": the sync worker, a one-person
# install, an export job. Those see everything, which is what they need.
viewer: ContextVar[int | None] = ContextVar("tally_viewer", default=None)


@contextmanager
def connection(as_person: int | None = None):
    who = as_person if as_person is not None else viewer.get()
    with state["pool"].connection() as conn:
        if who is not None:
            conn.execute("SELECT set_config('tally.viewer', %s, true)", (str(who),))
        yield conn


@contextmanager
def unscoped():
    """Explicitly everything, whoever is asking. For the things that are about
    the household as a whole -- the people list, the account-ownership editor --
    where filtering by the viewer would hide the very rows being managed."""
    with state["pool"].connection() as conn:
        yield conn
