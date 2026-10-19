# Univest notification bridge

This service reads a Univest push notification and, when the Kite desk is logged in, places the matching Zerodha limit order.

```json
{
  "symbol": "SBIN",
  "transaction_type": "BUY",
  "entry_price": 820.5,
  "stop_loss": 805.0,
  "target": 850.0,
  "source": "univest"
}
```

Extra fields may be included when the alert has them: `product` (`CNC`, `MIS`, or `NRML`), `targets` (every target, first one also copied to `target`), `entry_low` / `entry_high` when the alert gives a range, and `signal_kind` (`entry`, `partial_book`, or `exit`). A missing stop or target is `null`. An entry range uses the midpoint as `entry_price`.

## 1. Start the listener

From `jakshwealth-api`, for a test on this PC:

```powershell
python -m uvicorn kite_app.main:app --host 127.0.0.1 --port 8010 --reload --reload-dir kite_app
```

A phone on the same Wi-Fi cannot reach `127.0.0.1`. For MacroDroid or Tasker, set a secret and listen on the LAN address:

```powershell
$env:UNIVEST_INGEST_SECRET = "choose-a-long-secret"
python -m uvicorn kite_app.main:app --host 0.0.0.0 --port 8010 --reload --reload-dir kite_app
```

Find the PC address with `ipconfig`. Allow inbound TCP 8010 on private networks in Windows Firewall. The phone posts to `http://192.168.x.x:8010/api/univest/notification`.

Without `UNIVEST_INGEST_SECRET`, only this computer can submit alerts. A wrong or missing secret returns 401 and the alert is not parsed.

## 2. MacroDroid (recommended)

1. Install Univest (`com.univest.capp`) and sign in with your subscription.
2. Install MacroDroid and allow notification access when Android asks.
3. Create a macro.
4. Trigger: **Device Events → Notification → Notification Received**. Choose the Univest application.
5. Action: **Connectivity → HTTP Request**.
   - Method: `POST`
   - URL: `https://4jadhr4hk8.execute-api.ap-south-2.amazonaws.com/dev/jw-api/kite/api/univest/notification`
   - Content type: `text/plain`
   - Header: `X-Univest-Secret: choose-a-long-secret`
   - Body (MacroDroid magic text; `{not_text}` is not a real field):

```text
{not_title}
{notification}
{not_text_big}
{not_sub_text}
{not_text_lines}
```

6. Save the macro and send yourself a Univest test alert. The Kite desk **Univest** tab shows the parsed JSON. A malformed alert is logged and answered with `"accepted": false`. It does not stop the listener.

## 3. Tasker

1. Profile: **Event → UI → Notification**. Owner Application: Univest.
2. Task: **Net → HTTP Request**.
   - Method: `POST`
   - URL: `https://4jadhr4hk8.execute-api.ap-south-2.amazonaws.com/dev/jw-api/kite/api/univest/notification`
   - Headers: `X-Univest-Secret: choose-a-long-secret`
   - Body: `{"title":"%evtprm2","text":"%evtprm3"}`
3. Tasker notification text is `%evtprm3` and the title is `%evtprm2`.

## 4. Emulator option

BlueStacks plus Appium is only useful as a lab. A real phone with MacroDroid is more reliable because Android already delivers the notification.

If you still use an emulator:

1. Install Univest in BlueStacks and sign in.
2. Connect with `adb devices`.
3. Poll your own notification shade. Do not scrape the paid research screen.

```powershell
adb shell dumpsys notification --noredact
```

Copy the Univest title and text into the **Univest** tab, or POST them to `/api/univest/notification`. Appium is unnecessary for that step.

## 5. What the parser accepts

These shapes all parse:

- `BUY TATAMOTORS` with `Entry: 980-990`, `SL: 950`, `Target: 1050`, `CNC`
- No stop: `SELL RELIANCE` / `CMP 2460` / `Targets: 2400 / 2350 / 2300`
- Numbered targets: `T1: 850 T2: 870`
- Partial booking: `Book 50% profit in TATAMOTORS at 1020. Trail SL to cost.` This becomes `transaction_type: SELL` and `signal_kind: partial_book`
- Ticker in parentheses or after `NSE:`

The advisory cards use the same layout for every symbol:

- Futures: `RELIANCE 19 NOV FUT`, `Buy` or `Sell`, price, optional range, stoploss, target, `Lot size`
- Options: underlying name, then each leg `Buy 27 OCT 22750 PE 1 86.25`, then `Lot size`
- Stocks: `Stock - Long Term`, `Stock - Med. Term`, or `Stock - Short Term`, then the symbol, `Buy` or `Sell`, and the price

Text with no action, no ticker, or no price is rejected. The server logs a warning and keeps running. A logged-in Kite session is required before an order is sent.
