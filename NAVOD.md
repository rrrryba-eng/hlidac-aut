# Hlídač nových aut – návod

## 1. Nastav hledání
Na každém portálu (Sauto, TipCars, Bazoš, AutoScout24, mobile.de) si nastav filtry,
seřaď od nejnovějších a adresu z prohlížeče vlož do `config.yaml`.

## 2. GitHub
1. Založ si účet na github.com a vytvoř nový repozitář **Public**
   (veřejný má neomezené minuty zdarma; hesla a čísla jsou bezpečně v Secrets, ne v kódu).
   Chceš-li **Private**, změň v `.github/workflows/hlidac.yml` interval na `*/30` nebo `0 * * * *`,
   jinak vyčerpáš 2 000 bezplatných minut měsíčně.
2. Nahraj všechny soubory včetně složky `.github` (rozbal ZIP a přetáhni obsah do repozitáře).

## 3. Tajné údaje
Repozitář → Settings → Secrets and variables → Actions → New repository secret:

| Název | Hodnota |
|---|---|
| SMTP_HOST | `smtp.gmail.com` |
| SMTP_PORT | `465` |
| SMTP_USER | tvůj Gmail |
| SMTP_PASS | heslo aplikace (Google účet → Zabezpečení → dvoufázové ověření → Hesla aplikací) |
| EMAIL_TO | kam posílat (víc adres oddělit čárkou) |
| TWILIO_SID | Account SID z twilio.com |
| TWILIO_TOKEN | Auth Token z twilio.com |
| TWILIO_FROM | číslo/odesílatel z Twilia |
| SMS_TO | tvoje číslo ve tvaru `+420…` |

Bez Twilia to funguje jen s e-mailem (SMS se přeskočí). SMS přes Twilio je placená po kusech;
skript posílá max. 5 SMS za běh, zbytek je v e-mailu.

## 4. Test
Actions → **Hlidac aut** → Run workflow → zaškrtni **Testovací běh** → Run.
V logu kroku „Hlidani“ uvidíš, kolik inzerátů se na každém portálu našlo a jejich odkazy.

- **0 inzerátů nebo CHYBA** u portálu: portál pravděpodobně blokuje cloudové servery (typicky mobile.de)
  nebo změnil web. Pošli mi výpis z logu a doladíme `vzor`, případně ten portál pusť z vlastního PC (bod 6).
- Všechno vypadá dobře? Pusť jeden běh bez testu. První běh si jen zapamatuje stávající inzeráty
  a od dalšího ti chodí upozornění na nové.

## 5. Provoz
Běží samo každých 15 minut. Když se celý běh nepovede, GitHub ti pošle e-mail o chybě.

## 6. Alternativa: vlastní PC
```
pip install -r requirements.txt
python -m playwright install chromium
python hlidac.py --test
```
Údaje z tabulky nastav jako proměnné prostředí a `python hlidac.py` spouštěj přes Plánovač úloh ve Windows.
