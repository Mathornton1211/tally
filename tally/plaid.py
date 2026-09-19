"""Thin Plaid client over httpx.

Only read endpoints exist here. HANDOFF invariant 1: nothing that can move
money is ever added to this file.
"""
import httpx

PLAID_VERSION = "2020-09-14"


class PlaidError(Exception):
    def __init__(self, status: int, body: dict):
        self.status = status
        self.body = body
        self.code = body.get("error_code")
        super().__init__(f"{status} {self.code}: {body.get('error_message')}")


class Plaid:
    def __init__(self, host: str, client_id: str, secret: str, timeout: float = 30.0):
        self._auth = {"client_id": client_id, "secret": secret}
        self._http = httpx.Client(
            base_url=host,
            timeout=timeout,
            headers={"Plaid-Version": PLAID_VERSION},
        )

    def _post(self, path: str, body: dict) -> dict:
        r = self._http.post(path, json={**self._auth, **body})
        data = r.json()
        if r.status_code != 200:
            raise PlaidError(r.status_code, data)
        return data

    # Link
    def link_token_create(self, user_id: str, redirect_uri: str | None,
                          access_token: str | None = None) -> dict:
        body = {
            "user": {"client_user_id": user_id},
            "client_name": "Tally",
            "country_codes": ["US"],
            "language": "en",
        }
        if access_token:
            # Update mode: re-login for an existing Item. Products must be omitted.
            body["access_token"] = access_token
        else:
            body["products"] = ["transactions"]
            # Optional so an institution without liabilities (most checking-only
            # banks) is not hidden from the Link search.
            body["optional_products"] = ["liabilities", "investments"]
            body["transactions"] = {"days_requested": 730}
        if redirect_uri:
            body["redirect_uri"] = redirect_uri
        return self._post("/link/token/create", body)

    def public_token_exchange(self, public_token: str) -> dict:
        return self._post("/item/public_token/exchange", {"public_token": public_token})

    # Data
    def item_get(self, access_token: str) -> dict:
        return self._post("/item/get", {"access_token": access_token})

    def institution_get(self, institution_id: str) -> dict:
        return self._post("/institutions/get_by_id", {
            "institution_id": institution_id,
            "country_codes": ["US"],
        })

    def accounts_get(self, access_token: str) -> dict:
        return self._post("/accounts/get", {"access_token": access_token})

    def transactions_sync(self, access_token: str, cursor: str | None, count: int = 500) -> dict:
        # The bank's raw text ("ATM WITHDRAWAL 7-ELEVEN ... MX") is what fee and
        # fraud rules read. Plaid's cleaned `name` drops exactly those words.
        body = {"access_token": access_token, "count": count,
                "options": {"include_original_description": True}}
        if cursor:
            body["cursor"] = cursor
        return self._post("/transactions/sync", body)

    def liabilities_get(self, access_token: str) -> dict:
        """APRs, minimum payments and due dates. Not every institution supports
        it; callers treat PRODUCTS_NOT_SUPPORTED and NO_LIABILITY_ACCOUNTS as
        "this bank does not offer it", not as a failure."""
        return self._post("/liabilities/get", {"access_token": access_token})

    def investments_holdings_get(self, access_token: str) -> dict:
        return self._post("/investments/holdings/get", {"access_token": access_token})

    def investments_transactions_get(self, access_token: str, start: str, end: str, offset: int = 0) -> dict:
        return self._post("/investments/transactions/get", {
            "access_token": access_token, "start_date": start, "end_date": end,
            "options": {"count": 500, "offset": offset}})

    def transactions_refresh(self, access_token: str) -> dict:
        return self._post("/transactions/refresh", {"access_token": access_token})

    # Sandbox only
    def sandbox_public_token_create(self, institution_id: str, products: list[str]) -> dict:
        return self._post("/sandbox/public_token/create", {
            "institution_id": institution_id,
            "initial_products": products,
        })
