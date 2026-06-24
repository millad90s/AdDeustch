"""Static German grammar reference (Markdown bodies).

Grammar rules don't change, so this file is the curated source of truth. On first
run these topics are loaded into the `grammar` table; `add_grammar` upserts by
slug, so editing a body here and restarting with a fresh DB updates the content.

Each entry: (title, category, position, body_markdown).
Categories appear in the sidebar in the order their first topic's `position`
shows up, so positions are assigned as a sensible learning sequence.
"""

SEED_GRAMMAR = [
    # ===================== Grundlagen =====================
    ("Alphabet und Aussprache", "Grundlagen", 1, """
# Alphabet und Aussprache

German is largely phonetic — once you know the rules, you can read almost any
word. A few sounds differ from English:

| Buchstabe(n) | Aussprache | Beispiel |
| ------------ | ---------- | -------- |
| **ä** | like "e" in *bed* | M**ä**dchen |
| **ö** | like "i" in *bird* (rounded) | sch**ö**n |
| **ü** | "ee" with rounded lips | f**ü**nf |
| **ß** | sharp "s" (Eszett) | Fu**ß** |
| **ei** | "eye" | n**ei**n, dr**ei** |
| **ie** | long "ee" | v**ie**r, S**ie** |
| **eu / äu** | "oy" | n**eu**, l**äu**ft |
| **w** | English "v" | **W**asser |
| **v** | English "f" | **V**ater |
| **z** | "ts" | **Z**eit |
| **s** (before vowel) | "z" | **S**erver |
| **st / sp** (word start) | "sht / shp" | **St**unde, **Sp**rache |
| **ch** (after a/o/u) | throaty (as in *Bach*) | a**ch**t |
| **ch** (else) | soft "hush" | i**ch**, ni**ch**t |
| **j** | English "y" | **j**a |
| **-ig** (word end) | "ich" | wichti**g** |

> All **nouns are capitalized** in German — not just names: *der Server, die
> Besprechung, das Projekt.*
""".strip()),

    ("Artikel und Geschlecht (der, die, das)", "Grundlagen", 2, """
# Artikel und Geschlecht

Every German noun has a **gender**: *maskulin* (der), *feminin* (die) or
*neutral* (das). The article changes with gender — and later with case.

| Genus | bestimmter Artikel | unbestimmter Artikel | Beispiel |
| ----- | ------------------ | -------------------- | -------- |
| maskulin | der | ein | **der** Server |
| feminin  | die | eine | **die** Pipeline |
| neutral  | das | ein | **das** Projekt |
| Plural   | die | – (keine) | **die** Server |

**Tip:** always learn a noun *with* its article (e.g. *die Bereitstellung*, not
just *Bereitstellung*). The article carries the gender, which you need for cases
and adjective endings.

Helpful patterns:

- **-ung, -heit, -keit, -schaft, -tion, -ei** → usually *feminin*:
  *die Bereitstellung, die Sicherheit, die Konfiguration.*
- **-er** (people/tools), **-ig, -ling**, most engines/motors → often *maskulin*:
  *der Server, der Container, der Entwickler.*
- **-chen / -lein** (diminutives) → always *neutral*: *das Mädchen.*
- **-ment, -um, -ma** → often *neutral*: *das Dokument, das Datum.*
""".strip()),

    ("Pluralbildung", "Grundlagen", 3, """
# Pluralbildung

Unlike English (just add *-s*), German has several plural patterns. The plural
article is always **die**.

| Endung | Typisch für | Singular → Plural |
| ------ | ----------- | ----------------- |
| **-e** (often + Umlaut) | many maskulin | der Tag → die Tag**e**, der Plan → die Pl**ä**n**e** |
| **-(e)n** | most feminin | die Pipeline → die Pipeline**n**, die Frau → die Frau**en** |
| **-er** (+ Umlaut) | many neutral/maskulin | das Kind → die Kind**er**, das Buch → die B**ü**ch**er** |
| **-s** | foreign / abbreviations | das Auto → die Auto**s**, der Server → die Server**s**? → *die Server* |
| **– (no ending)**, sometimes Umlaut | maskulin/neutral ending in -er, -el, -en | der Container → die Container, der Apfel → die **Ä**pfel |

> There is no fully reliable rule — **learn the plural together with the noun**,
> e.g. *das Projekt, die Projekte.*
""".strip()),

    ("Die vier Fälle (Kasus)", "Grundlagen", 4, """
# Die vier Fälle

German has four cases. The case shows the **role** of a noun in the sentence and
changes the article.

| Fall | Frage | maskulin | feminin | neutral | Plural |
| ---- | ----- | -------- | ------- | ------- | ------ |
| **Nominativ** | wer/was? (subject) | der / ein | die / eine | das / ein | die |
| **Akkusativ** | wen/was? (direct object) | den / einen | die / eine | das / ein | die |
| **Dativ** | wem? (indirect object) | dem / einem | der / einer | dem / einem | den (+ -n) |
| **Genitiv** | wessen? (possession) | des (+ -s) | der | des (+ -s) | der |

**Beispiele**

- *Nominativ:* **Der Server** läuft.
- *Akkusativ:* Ich starte **den Server** neu.
- *Dativ:* Ich gebe **dem Entwickler** Zugriff.
- *Genitiv:* die Logs **des Servers**

> In spoken/technical German the Genitiv is often replaced by **von + Dativ**:
> *die Logs **vom** Server.*
""".strip()),

    ("Negation: nicht und kein", "Grundlagen", 5, """
# Negation: *nicht* und *kein*

German has two main ways to say "not / no".

**kein** negates a noun that has *ein* or no article. It declines like *ein*:

- Ich habe **einen** Fehler. → Ich habe **keinen** Fehler.
- Das ist **ein** Problem. → Das ist **kein** Problem.
- Wir haben **Zeit**. → Wir haben **keine** Zeit.

**nicht** negates everything else (verbs, adjectives, adverbs, or a noun with a
definite article). General position rules:

- At the **end** when it negates the whole sentence: *Ich verstehe das **nicht**.*
- **Before** the word it negates: *Das ist **nicht** wichtig.* / *Ich komme
  **nicht** heute.*
- **Before** a separable prefix or infinitive at the end: *Ich rufe dich **nicht**
  an.*

| | unbestimmt / ohne Artikel | bestimmt / sonst |
| - | ------------------------- | ---------------- |
| Negation | **kein** | **nicht** |
""".strip()),

    # ===================== Pronomen =====================
    ("Personalpronomen", "Pronomen", 6, """
# Personalpronomen

Personal pronouns also change by case.

| Nominativ | Akkusativ | Dativ |
| --------- | --------- | ----- |
| ich (I) | mich | mir |
| du (you, informal) | dich | dir |
| er (he/it) | ihn | ihm |
| sie (she/it) | sie | ihr |
| es (it) | es | ihm |
| wir (we) | uns | uns |
| ihr (you, plural) | euch | euch |
| sie (they) | sie | ihnen |
| Sie (you, formal) | Sie | Ihnen |

**Beispiele**

- **Ich** helfe **dir**. (*I help you.* — dir = Dativ)
- Kannst du **ihn** neu starten? (*Can you restart it?* — der Server → ihn)
- Ich schicke **ihnen** die Logs. (*I send them the logs.*)

> **du / ihr** = informal; **Sie** (always capitalized) = formal, for colleagues
> you don't know well, customers, etc.
""".strip()),

    ("Possessivartikel (mein, dein, …)", "Pronomen", 7, """
# Possessivartikel

Each personal pronoun has a matching possessive. They take the **same endings as
*ein* / *kein*** (depending on the gender, number and case of the noun owned).

| Person | Possessiv | Beispiel |
| ------ | --------- | -------- |
| ich | **mein** | mein Server |
| du | **dein** | dein Projekt |
| er / es | **sein** | sein Code |
| sie | **ihr** | ihr Team |
| wir | **unser** | unser Plan |
| ihr | **euer** | euer Build |
| sie (they) | **ihr** | ihr Ergebnis |
| Sie (formal) | **Ihr** | Ihr Zugang |

**Endings example (mein):**

- *Nominativ:* **mein** Server (m), **meine** Pipeline (f), **mein** Projekt (n), **meine** Server (pl)
- *Akkusativ:* **meinen** Server, **meine** Pipeline, **mein** Projekt
- *Dativ:* **meinem** Server, **meiner** Pipeline, **meinem** Projekt, **meinen** Servern
""".strip()),

    # ===================== Verben =====================
    ("Präsens: Verben konjugieren", "Verben", 8, """
# Präsens (Present Tense)

Regular verbs take the stem (infinitive minus **-en**) plus an ending:

| Person | Endung | *machen* (to do) | *arbeiten* (to work) |
| ------ | ------ | ---------------- | -------------------- |
| ich | -e | mach**e** | arbeit**e** |
| du | -st | mach**st** | arbeit**est** |
| er/sie/es | -t | mach**t** | arbeit**et** |
| wir | -en | mach**en** | arbeit**en** |
| ihr | -t | mach**t** | arbeit**et** |
| sie/Sie | -en | mach**en** | arbeit**en** |

*(Verbs whose stem ends in -t/-d add an extra **-e-**: du arbeit**e**st.)*

**Two essential irregular verbs**

| Person | *sein* (to be) | *haben* (to have) |
| ------ | -------------- | ----------------- |
| ich | bin | habe |
| du | bist | hast |
| er/sie/es | ist | hat |
| wir | sind | haben |
| ihr | seid | habt |
| sie/Sie | sind | haben |

> Some strong verbs change the stem vowel in *du* / *er-sie-es*: *fahren → du
> f**ä**hrst*, *geben → er g**i**bt*, *lesen → du l**ie**st.*
""".strip()),

    ("Modalverben", "Verben", 9, """
# Modalverben

Modal verbs (*können, müssen, wollen, sollen, dürfen, mögen*) express ability,
necessity, wish, etc. The **modal is conjugated in position 2**, and the **main
verb stays as an infinitive at the end**.

| | können | müssen | wollen | sollen | dürfen | mögen |
| - | ------ | ------ | ------ | ------ | ------ | ----- |
| ich | kann | muss | will | soll | darf | mag |
| du | kannst | musst | willst | sollst | darfst | magst |
| er/sie/es | kann | muss | will | soll | darf | mag |
| wir | können | müssen | wollen | sollen | dürfen | mögen |
| ihr | könnt | müsst | wollt | sollt | dürft | mögt |
| sie/Sie | können | müssen | wollen | sollen | dürfen | mögen |

**Beispiele**

- Ich **muss** heute das Release **vorbereiten**.
- **Kannst** du mir bei der Fehlersuche **helfen**?
- Wir **dürfen** in der Produktion nichts manuell **ändern**.

> Polite requests often use *möchte* (would like): *Ich **möchte** einen Termin
> **vereinbaren**.*
""".strip()),

    ("Trennbare Verben", "Verben", 10, """
# Trennbare Verben (Separable Verbs)

Many verbs have a **separable prefix** (*auf-, an-, mit-, zu-, ein-, vor-, …*).
In a main clause the prefix **splits off and goes to the end**.

- *aufstehen* → Ich **stehe** um 7 Uhr **auf**.
- *anrufen* → Ich **rufe** dich später **an**.
- *mitbringen* → **Bringst** du den Laptop **mit**?

In a **subordinate clause** the verb stays together at the end:

> …, weil ich um 7 Uhr **aufstehe**.

With a **modal verb**, it stays together as an infinitive:

> Ich muss früh **aufstehen**.

Common separable prefixes: **ab-, an-, auf-, aus-, bei-, ein-, mit-, nach-,
vor-, zu-, zurück-, zusammen-**.

> Note: **inseparable** prefixes (*be-, emp-, ent-, er-, ge-, ver-, zer-*) never
> split and form no *ge-* in Perfekt: *ver**stehen** → ich habe **verstanden**.*
""".strip()),

    ("Reflexive Verben", "Verben", 11, """
# Reflexive Verben

Reflexive verbs use a **reflexive pronoun** that refers back to the subject. Many
are *Akkusativ*; some take *Dativ* (when there is another direct object).

| Person | Akkusativ | Dativ |
| ------ | --------- | ----- |
| ich | mich | mir |
| du | dich | dir |
| er/sie/es | sich | sich |
| wir | uns | uns |
| ihr | euch | euch |
| sie/Sie | sich | sich |

**Beispiele**

- Ich **freue mich** auf das Projekt. (*I look forward to the project.*)
- Der Server **befindet sich** im Rechenzentrum. (*The server is located in the data center.*)
- Wir **konzentrieren uns** auf die Fehlerbehebung.
- Dativ: Ich **merke mir** das Passwort. (*I memorize the password.*)
""".strip()),

    ("Imperativ", "Verben", 12, """
# Imperativ (Commands)

Used for instructions and requests. There are three forms:

| Form | Bildung | Beispiel (*machen*) |
| ---- | ------- | ------------------- |
| **du** | stem (no ending) | **Mach** das Backup! |
| **ihr** | stem + **-t** | **Macht** das Backup! |
| **Sie** | infinitive + **Sie** | **Machen Sie** das Backup! |

**Irregular: *sein***

- du: **Sei** vorsichtig!
- ihr: **Seid** vorsichtig!
- Sie: **Seien Sie** vorsichtig!

**Beispiele**

- **Starte** den Dienst neu! (du)
- **Schaut** bitte ins Protokoll! (ihr)
- **Prüfen Sie** bitte die Konfiguration. (Sie)

> Add **bitte** to soften any command: *Hilf mir **bitte**.*
""".strip()),

    # ===================== Zeitformen =====================
    ("Perfekt (Vergangenheit)", "Zeitformen", 13, """
# Perfekt

The Perfekt is the everyday **spoken** past tense. It is built with a **helper
verb (haben / sein) in position 2** + the **Partizip II at the end**.

**Partizip II**

- Regular: **ge-** + stem + **-t** → *machen → gemacht*, *testen → getestet*
- Irregular (strong): **ge-** + stem + **-en** (often a vowel change) →
  *gehen → gegangen*, *schreiben → geschrieben*

**haben oder sein?**
Most verbs use **haben**. Use **sein** with verbs of **movement** or **change of
state** (*gehen, fahren, kommen, werden, passieren, bleiben*).

**Beispiele**

- Ich **habe** das Projekt **deployt**.
- Wir **haben** den Fehler **behoben**.
- Ich **bin** nach Berlin **gefahren**.
- Was **ist** passiert? — Der Server **ist** ausgefallen.
""".strip()),

    ("Präteritum", "Zeitformen", 14, """
# Präteritum (Simple Past)

The Präteritum is the **written** past tense (reports, stories, documentation).
In speech, *sein, haben* and modal verbs are commonly used in Präteritum, but
most other verbs use Perfekt.

**Regular verbs** add **-te-** + endings:

| Person | *machen* | Endung |
| ------ | -------- | ------ |
| ich | mach**te** | -te |
| du | mach**test** | -test |
| er/sie/es | mach**te** | -te |
| wir | mach**ten** | -ten |
| ihr | mach**tet** | -tet |
| sie/Sie | mach**ten** | -ten |

**The important irregulars**

| Person | *sein* | *haben* | *werden* |
| ------ | ------ | ------- | -------- |
| ich | war | hatte | wurde |
| du | warst | hattest | wurdest |
| er/sie/es | war | hatte | wurde |
| wir | waren | hatten | wurden |
| ihr | wart | hattet | wurdet |
| sie/Sie | waren | hatten | wurden |

> Strong verbs change the stem: *gehen → ging, kommen → kam, schreiben → schrieb.*
""".strip()),

    ("Futur (Zukunft)", "Zeitformen", 15, """
# Futur (Future)

**Futur I** = **werden** (position 2) + **infinitive** (at the end):

| Person | *werden* |
| ------ | -------- |
| ich | werde |
| du | wirst |
| er/sie/es | wird |
| wir | werden |
| ihr | werdet |
| sie/Sie | werden |

**Beispiele**

- Ich **werde** das morgen **prüfen**.
- Wir **werden** die neue Version nächste Woche **veröffentlichen**.

> In everyday German the **present tense + a time word** usually expresses the
> future: *Ich prüfe das **morgen**.* / *Nächste Woche **deployen** wir.* Futur I
> is used mainly for predictions or emphasis.
""".strip()),

    ("Konjunktiv II (Höflichkeit & Konditional)", "Zeitformen", 16, """
# Konjunktiv II

Used for **politeness**, **wishes** and **hypotheticals** ("would / could").
The everyday form is **würde + infinitive**; common verbs have their own form.

| Verb | Konjunktiv II |
| ---- | ------------- |
| sein | wäre |
| haben | hätte |
| werden | würde |
| können | könnte |
| müssen | müsste |
| sollen | sollte |

**Höfliche Bitten (polite requests)**

- **Könnten** Sie mir bitte helfen? (*Could you please help me?*)
- Ich **hätte** gern mehr Informationen. (*I would like more information.*)
- Es **wäre** gut, das vorher zu testen.

**Konditional**

- Wenn ich Zeit **hätte**, **würde** ich das Refactoring **machen**.
- An deiner Stelle **würde** ich zuerst die Logs **prüfen**.
""".strip()),

    # ===================== Präpositionen =====================
    ("Präpositionen mit Akkusativ und Dativ", "Präpositionen", 17, """
# Präpositionen mit festem Kasus

Some prepositions **always** take the Akkusativ, others **always** the Dativ.

**Immer Akkusativ** — *durch, für, gegen, ohne, um* (+ *bis, entlang*).
Mnemonic **DOGFU**: durch, ohne, gegen, für, um.

- Das ist **für dich**. — Wir gehen **durch den Tunnel**. — **ohne mich**.

**Immer Dativ** — *aus, außer, bei, gegenüber, mit, nach, seit, von, zu*.

- Ich fahre **mit dem Auto**. — **nach der Besprechung** — **seit einem Jahr** —
  **beim Kunden** (bei + dem).

**Häufige Verschmelzungen (contractions)**

| Präposition + Artikel | Kurzform |
| --------------------- | -------- |
| zu + dem | **zum** |
| zu + der | **zur** |
| bei + dem | **beim** |
| von + dem | **vom** |
""".strip()),

    ("Wechselpräpositionen", "Präpositionen", 18, """
# Wechselpräpositionen (Two-Way)

Nine prepositions take **either Akkusativ or Dativ** depending on meaning:

> **an, auf, hinter, in, neben, über, unter, vor, zwischen**

| Frage | Bedeutung | Kasus | Beispiel |
| ----- | --------- | ----- | -------- |
| **Wohin?** | movement / direction | **Akkusativ** | Ich lege die Datei **in den Ordner**. |
| **Wo?** | location / position | **Dativ** | Die Datei ist **in dem Ordner**. |

**More examples**

- Wohin? — Ich gehe **in die Besprechung** (Akk).
- Wo? — Ich bin **in der Besprechung** (Dat).
- Der Server steht **im Rechenzentrum** (Wo? → Dat, *in dem → im*).

**Verschmelzungen**: *an + dem → am, an + das → ans, in + dem → im, in + das → ins.*
""".strip()),

    # ===================== Adjektive =====================
    ("Adjektivdeklination", "Adjektive", 19, """
# Adjektivdeklination

When an adjective stands **before a noun**, it takes an ending. The ending
depends on the article in front of it. (Adjectives after *sein/werden* take **no**
ending: *Der Code ist **sauber**.*)

**1. After a definite article** (der/die/das, dieser…) — "weak":

| | maskulin | feminin | neutral | Plural |
| - | -------- | ------- | ------- | ------ |
| Nom | der gut**e** | die gut**e** | das gut**e** | die gut**en** |
| Akk | den gut**en** | die gut**e** | das gut**e** | die gut**en** |
| Dat | dem gut**en** | der gut**en** | dem gut**en** | den gut**en** |
| Gen | des gut**en** | der gut**en** | des gut**en** | der gut**en** |

**2. After ein/kein/mein…** — "mixed" (Nominativ/Akkusativ):

| | maskulin | feminin | neutral |
| - | -------- | ------- | ------- |
| Nom | ein gut**er** | eine gut**e** | ein gut**es** |
| Akk | einen gut**en** | eine gut**e** | ein gut**es** |

**3. No article** — "strong" (the adjective shows the case), Nominativ:

- gut**er** Code (m), gut**e** Arbeit (f), gut**es** Ergebnis (n), gut**e** Server (pl).

> Rule of thumb: if the article already shows the case, the adjective is "lazy"
> (**-e** or **-en**). If there is no article, the adjective must do the work.
""".strip()),

    ("Komparativ und Superlativ", "Adjektive", 20, """
# Komparativ und Superlativ

**Comparative** = adjective + **-er** (+ *als* for "than").
**Superlative** = **am** + adjective + **-sten** (or *der/die/das …-ste* before a noun).

| Grundform | Komparativ | Superlativ |
| --------- | ---------- | ---------- |
| schnell | schnell**er** | am schnell**sten** |
| klein | klein**er** | am klein**sten** |
| gut | **besser** | am **besten** |
| viel | **mehr** | am **meisten** |
| gern | **lieber** | am **liebsten** |
| hoch | **höher** | am **höchsten** |
| groß | größer | am größten |

**Beispiele**

- Diese Lösung ist **schneller als** die alte.
- Welche Methode ist **am sichersten**?
- Das ist der **beste** Ansatz. (before a noun → *der beste*)

> Short adjectives with a/o/u often add an **Umlaut**: *alt → älter, groß → größer,
> jung → jünger.*
""".strip()),

    # ===================== Syntax =====================
    ("Wortstellung (Satzbau)", "Syntax", 21, """
# Wortstellung

**Rule 1 — the conjugated verb is in position 2** in a main clause:

> *Ich* **deploye** *die neue Version heute Abend.*
> *Heute Abend* **deploye** *ich die neue Version.* (something else first → verb still 2nd, subject moves after)

**Rule 2 — order of extra info: TeKaMoLo**
*Temporal (when) → Kausal (why) → Modal (how) → Lokal (where).*

> Ich fahre **heute** (Te) **wegen des Termins** (Ka) **mit dem Auto** (Mo)
> **nach Berlin** (Lo).

**Rule 3 — subordinate clauses send the verb to the end** (after *weil, dass,
wenn, ob…*):

> Die Pipeline schlägt fehl, **weil** ein Test nicht **besteht**.

**Yes/no questions** put the verb first:

> **Läuft** der Build? — **Hast** du den Fehler behoben?
""".strip()),

    ("Nebensätze und Konjunktionen", "Syntax", 22, """
# Nebensätze und Konjunktionen

**Coordinating conjunctions** join two main clauses and **do not change** word
order: *und, aber, oder, denn, sondern.*

> Ich prüfe die Logs, **und** du startest den Dienst neu.

**Subordinating conjunctions** start a subordinate clause and send the conjugated
verb **to the end**: *weil, dass, wenn, als, ob, obwohl, damit, bevor, nachdem,
während.*

> Ich glaube, **dass** der Build gleich fertig **ist**.
> **Wenn** das Deployment **fehlschlägt**, rollen wir zurück.

> When the subordinate clause comes first, the main clause starts with its verb
> (the whole clause is "position 1"): *Weil ein Test fehlschlägt, **schlägt** die
> Pipeline fehl.*

**Conjunctional adverbs** (*deshalb, deswegen, trotzdem, dann, sonst*) count as
position 1, so the verb follows immediately (inversion):

> Der Test ist rot, **deshalb deploye** ich nicht.
""".strip()),

    ("Fragen (W-Fragen & Ja/Nein-Fragen)", "Syntax", 23, """
# Fragen

**Ja/Nein-Fragen** — verb first:

> **Läuft** der Server? — **Hast** du Zeit? — **Können** wir das testen?

**W-Fragen** — question word, then the verb in position 2:

| W-Wort | Bedeutung | Beispiel |
| ------ | --------- | -------- |
| wer | who | **Wer** ist zuständig? |
| was | what | **Was** ist passiert? |
| wann | when | **Wann** ist die Besprechung? |
| wo | where | **Wo** sind die Logs? |
| wohin | where to | **Wohin** deployen wir? |
| woher | where from | **Woher** kommt der Fehler? |
| warum / wieso | why | **Warum** schlägt der Test fehl? |
| wie | how | **Wie** lange dauert der Build? |
| welch- | which | **Welche** Version läuft? |
| wie viel(e) | how much/many | **Wie viele** Server brauchen wir? |
""".strip()),

    # ===================== Alltag =====================
    ("Zahlen, Datum und Uhrzeit", "Alltag", 24, """
# Zahlen, Datum und Uhrzeit

**Zahlen**

- 0–12: null, eins, zwei, drei, vier, fünf, sechs, sieben, acht, neun, zehn, elf, zwölf
- 13–19: drei**zehn**, vier**zehn**, … neun**zehn**
- 20, 30…: zwanzig, dreißig, vierzig, … neunzig
- Compound (read units first!): 21 = **einundzwanzig**, 47 = **siebenundvierzig**
- 100 = (ein)hundert, 1000 = (ein)tausend, 1.000.000 = eine Million

**Ordinalzahlen** (1st, 2nd…): add **-te** (1–19) or **-ste** (from 20).
Irregular: 1. **erste**, 3. **dritte**, 7. **siebte**, 8. **achte**.

**Datum**

- — Welches Datum ist heute? — Heute ist **der 23. Juni** (*der dreiundzwanzigste Juni*).
- **Am** 23. Juni habe ich einen Termin. (*am dreiundzwanzigsten*)

**Uhrzeit**

| Zeit | Formell | Umgangssprachlich |
| ---- | ------- | ----------------- |
| 14:00 | vierzehn Uhr | zwei (Uhr) |
| 14:15 | vierzehn Uhr fünfzehn | Viertel nach zwei |
| 14:30 | vierzehn Uhr dreißig | halb drei |
| 14:45 | vierzehn Uhr fünfundvierzig | Viertel vor drei |

> Note: **halb drei** = 2:30 (literally "half *to* three"), not 3:30.
""".strip()),
]
