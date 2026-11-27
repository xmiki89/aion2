# Aion 2 Damage Meter

Damage meter desktop per Aion 2 (Windows), con la grafica delle foto: classifica del party,
dettaglio per giocatore, tab per danno/cura/danno subito, filtro Brawler (KR/TW), e overlay
trasparente sopra il gioco.

## Installazione (per chi riceve il file)

Manda all'amico **`dist\Aion2DamageMeter-Setup.exe`**: all'avvio chiede **in quale cartella installare**
(default `%LOCALAPPDATA%\Aion2DamageMeter`, con pulsante "Sfoglia…" per scegliere un altro disco),
offre i collegamenti su desktop e menu Start, e al termine può avviare subito il meter.
Il programma installato è un singolo file `Aion2DamageMeter.exe` nella cartella scelta.

Installazione silenziosa, senza finestre:

```
Aion2DamageMeter-Setup.exe --silent --dir "D:\Giochi\Aion2Meter" [--no-shortcuts] [--no-launch]
```

La stessa app si disinstalla da sola: App e funzionalità di Windows → Aion 2 Damage Meter →
Disinstalla, oppure `Aion2DamageMeter.exe --uninstall`. Vengono rimossi collegamenti, voce di
Windows e cartella; `combat.log` e `session.json` non vengono toccati.

## Avvio

- Doppio clic su `dist\Aion2DamageMeter.exe` (portable, nessuna installazione richiesta).
- In alternativa, dalla cartella del progetto: `python main.py`.
- `python main.py --demo` (o `Aion2DamageMeter.exe --demo`) riempie la finestra con una run finta,
  utile solo per provare l'interfaccia.

All'apertura la finestra è **vuota**: mostra "In attesa di Aion 2". Non ci sono dati finti, né
nomi, né classi preimpostate.

## Overlay in gioco (trasparente, sempre sopra)

- Pulsante **Overlay** nella barra dei filtri, oppure **Ctrl+Shift+O** mentre giochi.
- Finestra senza bordi, sempre in primo piano, semitrasparente: righe compatte con nome, classe,
  DPS e percentuale, più il DPS totale del gruppo e un pallino verde quando i dati sono live.
- Si trascina col mouse; la rotella cambia la trasparenza; doppio clic riporta la finestra
  principale in primo piano; clic destro → menu con "Apri finestra", "Trasparenza" (100/90/80/70/55%),
  "Nascondi overlay". Posizione e trasparenza vengono ricordate in
  `%LOCALAPPDATA%\Aion2DamageMeter\overlay.json`.
- Nota: gli overlay Windows non compaiono sopra i giochi in esclusiva fullscreen. Imposta Aion 2 in
  **finestra senza bordi / borderless** (o finestra) e l'overlay resta visibile.

## Cosa succede da solo

1. Ogni 2 secondi il meter cerca il client (`aion2.exe`, `aion2client.exe`, `aion2_x64.exe`, …).
   Appena lo trova lo segnala nella barra in basso con PID, server e personaggio.
2. **Classe del tuo personaggio**: viene presa dal feed (`session`), dal file `session.json`, dal
   titolo della finestra di gioco e, se non basta, da una scansione locale dei file di
   configurazione/log del client (cartella di installazione, `%LOCALAPPDATA%`, `%APPDATA%`,
   `Documenti`). Il risultato appare nel chip "Tu: Nome · Classe".
3. **Membri del dungeon**: ogni evento `join`/`party` aggiunge la riga subito, anche a 0 danni; ogni
   nuovo giocatore che colpisce viene aggiunto automaticamente; `leave` rimuove chi esce.
4. Cliccando su un nome si apre il dettaglio: nome, classe, archetipo, DPS e percentuale, Crit Rate,
   Double Hit, Multi-Hit, Back Attack, barra Back/Front-Flank e tabella delle abilità usate con
   colpi, danno, share, BACK % e MULT %.

Il badge in alto a destra resta **DEMO** finché non arrivano eventi reali, poi passa a **LIVE**.

## Aggiornamenti automatici

Chi ha già l'app non deve fare nulla: circa 2 secondi dopo l'avvio il meter legge `version.json`
da `https://raw.githubusercontent.com/xmiki89/aion2/main`, confronta la versione con la propria e, se
è più vecchia, scarica la nuova build **da solo**, la verifica (dimensione + SHA-256), sostituisce
l'eseguibile e **riapre l'app** già aggiornata. Il chip accanto al badge mostra "Aggiorno a …%" e poi
"Riavvio…"; se il download non riesce diventa "Riprova aggiornamento" (un clic).

Se la rete o GitHub non rispondono l'app funziona normalmente e riprova al prossimo avvio.
Controllo manuale: `python main.py --check-update` oppure `Aion2DamageMeter.exe --update`.

## Feed dati (per i numeri di danno)

Il meter legge un file JSON Lines, una riga per evento. Posizione cercata, in ordine:

1. variabile d'ambiente `AION2METER_LOG`
2. `combat.log` accanto all'exe
3. `%LOCALAPPDATA%\Aion2DamageMeter\combat.log`
4. `Documenti\Aion2DamageMeter\combat.log`

Se il file compare mentre il meter è già aperto, viene collegato da solo (entro 2 secondi).

Formato righe:

```json
{"type":"session","server":"Siel","character":"Lyra","class":"Sorcerer"}
{"type":"party","members":[{"name":"Vex","class":"Assassin","role":"DPS"},{"name":"Aegis","class":"Templar","role":"Tank"}]}
{"type":"join","name":"Sora","class":"Chanter","role":"Support"}
{"type":"leave","name":"Sora"}
{"type":"hit","t":12.4,"src":"Lyra","class":"Sorcerer","skill":"Arcane Implosion","amount":31200,"crit":true,"double":false,"multi":false,"position":"back"}
{"type":"heal","t":13.0,"src":"Elara","class":"Cleric","skill":"Healing Light","amount":8200}
{"type":"taken","t":13.6,"src":"Aegis","class":"Templar","skill":"Boss Slam","amount":18400}
{"type":"hit","t":14.1,"src":"Earth Spirit","class":"Spiritmaster","pet":true,"owner":"Sylphie","skill":"Spirit Claw","amount":6100}
```

- `position`: `back`, `front`, `flank` (usato per Back %).
- `crit` / `double` / `multi`: flag dei colpi.
- `pet: true` + `owner`: il danno dei pet/evocazioni viene ignorato dal meter (non entra
  né nel totale né nelle righe).
- `t`: secondi dall'inizio del combattimento. Se manca, il meter prosegue con il proprio clock.

Sessione (server, personaggio, classe) alternativa, senza log:

```json
{"server":"Siel","character":"Nyx","class":"Sorcerer"}
```

in `session.json` accanto all'exe, in `%LOCALAPPDATA%\Aion2DamageMeter\` o in
`Documenti\Aion2DamageMeter\`.

## Limite importante

Aion 2 non espone una API di combattimento pubblica: il meter non legge la memoria del client e non
intercetta il traffico di rete. Rilevamento del processo, del server e del personaggio sono
automatici; i **numeri di danno** e l'elenco dei membri che entrano nel dungeon arrivano dal feed
qui sopra. Il rilevamento della classe dai file locali è euristico: se il client non salva testi
leggibili, la classe viene presa dal feed.

## Build

```
python -m pip install pyinstaller
python build.py
```

Vengono creati `dist\Aion2DamageMeter.exe` (app) e `dist\Aion2DamageMeter-Setup.exe` (installer con
scelta della cartella, che incorpora l'app).

## Pubblicare una modifica

```
python tools/sync.py -m "descrizione della modifica"
```

Fa tutto in un colpo: incrementa la versione patch, ricompila app e installer, aggiorna
`update/Aion2DamageMeter.exe` e `version.json` (con SHA-256 e dimensione), crea il commit e fa
`git push` su `origin main`. Se non ci sono modifiche ai file non fa nulla; con `--no-push` fa solo
il commit locale. Dopo il push, chi ha l'app vede il pulsante **Aggiorna** al successivo avvio.

Il repository è https://github.com/xmiki89/aion2 (pubblico, così il controllo aggiornamenti
funziona senza token).
