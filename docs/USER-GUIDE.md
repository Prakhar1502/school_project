# School Fee Register — user guide

Keep student details and fees on your own laptop, and update them from your phone over Wi‑Fi. Free, no internet account needed, and the data never leaves the laptop.

## What's in this folder

| File | What it is |
|---|---|
| `start-windows.bat` | Double-click this to start the register on Windows |
| `start-mac-linux.sh` | The same for Mac or Linux |
| `server.py` | The small program that runs the register (Python) |
| `index.html` | The register's screens |
| `data/` | Created on first start: all your students, payments and daily backups |

## One-time setup (about 10 minutes)

1. **Install Python** (free) from <https://www.python.org/downloads/>.
   On Windows, **tick "Add python.exe to PATH"** on the first install screen.
2. Copy this whole folder somewhere permanent, for example `Documents\School Fee Register`.
3. Double-click **`start-windows.bat`**.
4. A black window opens and asks you to **choose a PIN** (4–12 digits). Type it twice.
5. The register opens in the browser. Enter the PIN.
6. If Windows asks whether to allow Python on networks, choose **Allow** for **Private networks**. This is what lets the phone connect.
7. Go to **Settings**: set the school name, the session start, and the **monthly fee for each class**.
8. Add students on the **Students** page, or import them from Excel (**Import CSV**).

## Using it on the phone

1. Connect the phone to the **same Wi‑Fi** as the laptop.
2. On the laptop, open **Settings → Use on your phone**. Scan the QR code with the phone camera, or type the address shown (it looks like `http://192.168.1.5:8000`).
3. Enter the PIN once. The phone stays signed in.
4. In Chrome on the phone, tap **⋮ → Add to Home screen**, so the register opens like an app.

Any change made on the phone shows up on the laptop within a few seconds, and the other way round.

**The laptop must be switched on with the black register window open.** If the phone says "Can't reach the laptop", check those two things and the Wi‑Fi.

> If the phone address stops working after a few days, the router may have given the laptop a new address. Open **Settings** on the laptop to see the new one. To stop this happening, ask whoever set up your Wi‑Fi to "reserve an IP address" for the laptop.

## Start automatically when the laptop turns on (Windows)

1. Right-click `start-windows.bat` → **Create shortcut**.
2. Press **Windows key + R**, type `shell:startup`, press Enter.
3. Move the shortcut into the folder that opens.

## Fees: class fee or custom fee

Each student has one of two fee types:

- **Same as class fee:** uses the class fee from Settings. Change the class fee once and every student on it updates.
- **Custom fee for this student:** for discounts, siblings, scholarships or transport. Settings changes don't affect it.

Changing a fee recalculates the whole current session at the new rate. Change fees at the start of a session where possible.

## Fee receipts (PDF)

Every payment gets a printable A5 PDF receipt. It shows the school name and address, the receipt number, the student, which months the payment covered, the amount in words, the balance left, and a PAID stamp.

- **Right after a payment:** the receipt opens automatically.
- **Any time later:** tap a payment on the **Payments** page, or press **Receipt** next to a payment in a student's details.
- **Download PDF** saves it. On the laptop, **Open PDF** shows it in a new tab, where you can print it.
- **Sending on WhatsApp from the phone:** tap **Download PDF**, then **Open WhatsApp chat**. In the chat, tap 📎 → **Document** and pick the receipt from Downloads.
- **On the laptop**, a **Share PDF to WhatsApp** button may also appear. It sends the file directly if WhatsApp Desktop is installed.
- **All receipts at once:** on the **Payments** page, choose a period, then **All receipts (PDF)**. You get one PDF with one receipt per page.
- Set the address, signatory name and a bottom note in **Settings → School and session**.

## Backups

- A copy of the data is saved every day in `data/backups/` (the last 60 days are kept).
- For extra safety, copy the `data` folder to a pen drive or Google Drive now and then.
- To restore a backup: close the register, replace `data/fees.db` with a backup file renamed to `fees.db`, and start again.
- **Payments → Export CSV** saves everything as a spreadsheet that opens in Excel.

## Moving to a new laptop

Install Python on the new laptop, copy this whole folder including `data`, and double-click `start-windows.bat`.

## Forgot the PIN

Open a terminal in this folder and run:

```
python server.py --reset-pin
```

This signs out every device, and each one needs the new PIN.

## Other options

```
python server.py --port 8001     use a different port if 8000 is busy
python server.py --no-browser    start without opening the browser
```

## Using it away from the school Wi‑Fi (optional, advanced)

The register only works on the same Wi‑Fi as the laptop, which keeps it private. If you really need it from anywhere, Cloudflare's free tunnel can give it a temporary public address:

```
cloudflared tunnel --url http://localhost:8000
```

Anyone with that address still needs the PIN, so choose a PIN that isn't easy to guess. The address changes each time the tunnel restarts.
