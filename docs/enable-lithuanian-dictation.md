# Įjungti lietuvių kalbos diktavimą (macOS)

Ši trumpa instrukcija padės įjungti lietuvių kalbos diktavimą tavo Mac (norint, kad Lani galėtų atpažinti lietuvišką balsą).

## 1) Sisteminiai nustatymai (macOS Ventura ir naujesnės)

1. Atidaryk System Settings (Sistemos nustatymai).
2. Eik į Keyboard -> Dictation.
3. Įjunk Dictation (jei dar išjungta).
4. Pasirink „Language“ ir pridėk „Lithuanian (Lithuania) - lt-LT" (jei nėra, įsitikink, kad macOS turi lietuvių kalbos paketą).
5. Leisk prieigą prie mikrofono, jei sistema to paprašo.

Pastaba: kai kurie WebView arba Tauri renderer'iai gali naudoti savo Web Speech API implementaciją (arba priklausyti nuo WKWebView). Sistemos diktavimas yra atskiras komponentas, tačiau pridėjus `lt-LT` į sistemos kalbas, dažnai pagerėja transkripcija ir naršyklės atpažinimas.

## 2) Leidimai (mikrofonas)

- Atidaryk System Settings -> Privacy & Security -> Microphone.
- Patikrink, ar tavo aplikacija (Tauri app arba naršyklė) turi leidimą naudoti mikrofoną.
- Jei leidimas yra atjungtas, įjunk jį ir perkrauk programą.

## 3) Lani (frontend) konfigūracija

- Lani naudoja Web Audio / MediaRecorder naršyklėje ir siunčia garso paketus į backend `/api/v1/voice/transcribe`.
- Frontende numatytoji diktavimo kalba yra `lt-LT`. Jei nori pakeisti, atidaryk `apps/desktop/src/hooks/useContinuousVoice.ts` ir pakeisk `language` parametrą (BCP-47 formatu), pvz. `lt-LT`.
- Jei tavo WebView nepalaiko `window.SpeechRecognition`, Lani naudoja MediaRecorder + server-side STT (pvz. OpenAI Whisper). Backend normalizuoja kalbos žymę (`lt-LT` → `lt`) kai palaikomas provider'is.

## 4) Jei nori geresnės kokybės

- Apsvarstyk papildomą STT tiekėją (pvz., OpenAI Whisper via `OPENAI_API_KEY` arba ElevenLabs TTS) — įdėjus API raktą serverio `.env` faile ir perkraunus backend, Lani automatiškai naudos tą tiekėją.
- ElevenLabs turi gerą daugakalbę TTS palaikymą; Whisper (OpenAI) paprastai gerai atpažįsta lietuvių kalbą su `lang='lt'` parametru.

## 5) Testavimo žingsniai

1. Atidaryk aplikaciją.
2. Patikrink, ar naršyklė/Tauri paprašo mikrofono leidimo — sutik su juo.
3. Paleisk Lani balsu (wake word arba mikrofono mygtukas) ir pasakyk: „labas Lani, ar girdžiu tave?“ arba „atidaryk gmail ir perskaityk paskutinius laiškus".
4. Jei transkripcija netiksli, patikrink System Settings -> Keyboard -> Dictation language ir įsitikink, kad `lt-LT` pasirinkta.

## 6) Dažnos problemos

- Jei matote tuščią transkriptą arba „provider_not_configured" atsakymą, backend'e nėra sukonfigūruoto STT tiekėjo. Patikrink `.env` ar nustatyti `OPENAI_API_KEY` arba kitas `VOICE_PROVIDER` nustatymai.
- Jei WebView neturi `SpeechRecognition` API (pvz., senesnė WKWebView versija), Lani vis tiek gali dirbti per MediaRecorder → server-side STT.

---

Jei nori, galiu šias instrukcijas įdėti į UI kaip „Help" skyrelį arba parodyti trumpą demo mygtuką, kuris pradeda diktavimą su `lt-LT` ir rodo transkripciją realiu laiku.