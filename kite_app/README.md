# JakshWealth Kite desk

Local Python FastAPI backend for Zerodha Kite Connect. The Angular UI in `jakshwealth-ui` is the frontend.

The access token is written to `jakshwealth-api/.kite/session.json` and is never returned to the browser. Restarting either app reuses that file, so you do not log in again after every code change. A Kite access token still expires once a day; when it does, sign in again with a new request token.

## 1. Backend

From `jakshwealth-api`:

```powershell
python -m pip install -r kite_app/requirements.txt
python -m uvicorn kite_app.main:app --host 127.0.0.1 --port 8010 --reload --reload-dir kite_app
```

The API listens on http://127.0.0.1:8010. Interactive docs: http://127.0.0.1:8010/docs

## 2. Frontend

From `jakshwealth-ui`, create the local environment file once if it is missing:

```powershell
copy src\environments\environment.development.example.ts src\environments\environment.development.ts
npm install
npm start
```

Open http://localhost:4200/kite/login

## 3. Sign in

1. In the [Kite developer console](https://developers.kite.trade/), confirm the app is Active and the Zerodha client ID matches the account you will use.
2. Open `https://kite.zerodha.com/connect/login?api_key=YOUR_API_KEY&v=3`
3. After Zerodha redirects, copy the `request_token` from the URL (or paste the whole URL).
4. Enter the API key, API secret, and request token, then choose Login.

The dashboard User tab shows your name, user ID, products, and exchanges. Market shows live NSE quotes. Signals scans the official Nifty 100 list for SMA, EMA, or WMA crossovers on daily Kite candles.

## Customize

Dashboard colors come from the variables at the top of `jakshwealth-ui/src/styles.css` (`--jw-bg-deep`, `--jw-cyan`, and the rest). The API address is `KITE_API_BASE` in `jakshwealth-ui/src/app/features/kite-desk/kite.api.ts`.

Do not commit `.kite/session.json` or your API secret.
