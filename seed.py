"""Starter flashcards: German DevOps / team-lead vocabulary, learned in context.

Each entry is a word with one or more example sentences. At review time one
sentence is shown at random.
"""

SEED_WORDS = [
    # # --- devops ---
    # {"word": "die Bereitstellung", "category": "devops", "level": "B1", "sentences": [
    #     ("Die Bereitstellung der neuen Version ist für heute Abend geplant.",
    #      "The deployment of the new version is planned for this evening."),
    #     ("Die Bereitstellung schlug fehl und wurde sofort zurückgerollt.",
    #      "The deployment failed and was rolled back immediately."),
    # ]},
    # {"word": "die Pipeline", "category": "devops", "level": "B1", "sentences": [
    #     ("Die Pipeline schlägt fehl, weil ein Test nicht besteht.",
    #      "The pipeline fails because a test does not pass."),
    #     ("Nach jedem Commit läuft die Pipeline automatisch.",
    #      "After every commit the pipeline runs automatically."),
    # ]},
    # {"word": "der Build", "category": "devops", "level": "B1", "sentences": [
    #     ("Der Build wurde erfolgreich abgeschlossen und kann getestet werden.",
    #      "The build was completed successfully and can be tested."),
    # ]},
    # {"word": "die Umgebung", "category": "devops", "level": "B1", "sentences": [
    #     ("Wir testen die Änderung zuerst in der Staging-Umgebung.",
    #      "We test the change first in the staging environment."),
    #     ("In der Produktionsumgebung dürfen wir nichts manuell ändern.",
    #      "In the production environment we must not change anything manually."),
    # ]},
    # {"word": "zurückrollen", "category": "devops", "level": "B1", "sentences": [
    #     ("Wenn die Bereitstellung fehlschlägt, müssen wir die Version zurückrollen.",
    #      "If the deployment fails, we have to roll back the version."),
    # ]},
    # {"word": "der Container", "category": "devops", "level": "B1", "sentences": [
    #     ("Jeder Dienst läuft in einem eigenen Container.",
    #      "Each service runs in its own container."),
    # ]},
    # {"word": "die Überwachung", "category": "devops", "level": "B2", "sentences": [
    #     ("Die Überwachung hat einen Anstieg der Fehlerrate gemeldet.",
    #      "The monitoring reported an increase in the error rate."),
    # ]},
    # {"word": "die Abhängigkeit", "category": "devops", "level": "B2", "sentences": [
    #     ("Diese Abhängigkeit muss vor dem nächsten Release aktualisiert werden.",
    #      "This dependency must be updated before the next release."),
    # ]},
    # {"word": "der Zweig", "category": "devops", "level": "B1", "sentences": [
    #     ("Bitte erstelle einen neuen Zweig für diese Funktion.",
    #      "Please create a new branch for this feature."),
    # ]},
    # {"word": "die Sicherung", "category": "devops", "level": "B1", "sentences": [
    #     ("Wir erstellen jede Nacht eine Sicherung der Datenbank.",
    #      "We create a backup of the database every night."),
    # ]},
    # {"word": "die Skalierung", "category": "devops", "level": "B2", "sentences": [
    #     ("Die automatische Skalierung fügt bei hoher Last weitere Server hinzu.",
    #      "Auto-scaling adds more servers under high load."),
    # ]},
    # {"word": "die Verfügbarkeit", "category": "devops", "level": "B2", "sentences": [
    #     ("Unser Ziel ist eine Verfügbarkeit von 99,9 Prozent.",
    #      "Our goal is an availability of 99.9 percent."),
    # ]},

    # # --- incident ---
    # {"word": "der Ausfall", "category": "incident", "level": "B1", "sentences": [
    #     ("Der Ausfall hat etwa zwanzig Minuten gedauert.",
    #      "The outage lasted about twenty minutes."),
    # ]},
    # {"word": "die Störung", "category": "incident", "level": "B1", "sentences": [
    #     ("Wir untersuchen derzeit eine Störung im Zahlungssystem.",
    #      "We are currently investigating an incident in the payment system."),
    # ]},
    # {"word": "die Ursache", "category": "incident", "level": "B1", "sentences": [
    #     ("Die Ursache des Problems war eine falsche Konfiguration.",
    #      "The cause of the problem was a wrong configuration."),
    #     ("Wir suchen noch nach der eigentlichen Ursache des Ausfalls.",
    #      "We are still looking for the actual cause of the outage."),
    # ]},
    # {"word": "beheben", "category": "incident", "level": "A2", "sentences": [
    #     ("Wir haben den Fehler behoben und das System läuft wieder.",
    #      "We have fixed the error and the system is running again."),
    # ]},
    # {"word": "die Auswirkung", "category": "incident", "level": "B1", "sentences": [
    #     ("Die Auswirkung auf die Nutzer war zum Glück gering.",
    #      "The impact on the users was fortunately small."),
    # ]},
    # {"word": "dringend", "category": "incident", "level": "A2", "sentences": [
    #     ("Dieses Problem ist dringend und muss sofort gelöst werden.",
    #      "This problem is urgent and must be solved immediately."),
    # ]},

    # # --- team-lead ---
    # {"word": "die Verantwortung", "category": "team-lead", "level": "B1", "sentences": [
    #     ("Als Teamleiter übernehme ich die Verantwortung für das Ergebnis.",
    #      "As a team lead, I take responsibility for the result."),
    # ]},
    # {"word": "die Frist", "category": "team-lead", "level": "B1", "sentences": [
    #     ("Wir müssen die Frist für das Projekt einhalten.",
    #      "We have to meet the deadline for the project."),
    # ]},
    # {"word": "die Priorität", "category": "team-lead", "level": "B1", "sentences": [
    #     ("Lass uns die Aufgaben nach Priorität ordnen.",
    #      "Let's order the tasks by priority."),
    # ]},
    # {"word": "die Rückmeldung", "category": "team-lead", "level": "B1", "sentences": [
    #     ("Ich gebe dir bis morgen eine Rückmeldung zu deinem Vorschlag.",
    #      "I will give you feedback on your proposal by tomorrow."),
    # ]},
    # {"word": "zuständig", "category": "team-lead", "level": "B1", "sentences": [
    #     ("Wer ist für die Code-Überprüfung zuständig?",
    #      "Who is responsible for the code review?"),
    # ]},
    # {"word": "der Aufwand", "category": "team-lead", "level": "B1", "sentences": [
    #     ("Wie hoch ist der Aufwand für diese Aufgabe?",
    #      "How much effort is required for this task?"),
    # ]},
    # {"word": "vereinbaren", "category": "team-lead", "level": "B1", "sentences": [
    #     ("Können wir einen Termin für nächste Woche vereinbaren?",
    #      "Can we arrange an appointment for next week?"),
    # ]},
    # {"word": "unterstützen", "category": "team-lead", "level": "B1", "sentences": [
    #     ("Ich kann dich bei der Fehlersuche unterstützen.",
    #      "I can support you with the troubleshooting."),
    # ]},

    # # --- meetings ---
    # {"word": "die Besprechung", "category": "meetings", "level": "A2", "sentences": [
    #     ("Die Besprechung beginnt um zehn Uhr im großen Raum.",
    #      "The meeting starts at ten o'clock in the big room."),
    # ]},
    # {"word": "die Tagesordnung", "category": "meetings", "level": "A2", "sentences": [
    #     ("Was steht heute auf der Tagesordnung?",
    #      "What is on the agenda today?"),
    # ]},
    # {"word": "der Stand", "category": "meetings", "level": "A2", "sentences": [
    #     ("Kannst du uns einen kurzen Stand zu deiner Aufgabe geben?",
    #      "Can you give us a short status update on your task?"),
    # ]},
    # {"word": "klären", "category": "meetings", "level": "A2", "sentences": [
    #     ("Diese Frage müssen wir in der nächsten Besprechung klären.",
    #      "We have to clarify this question in the next meeting."),
    # ]},
    # {"word": "der Vorschlag", "category": "meetings", "level": "A2", "sentences": [
    #     ("Dein Vorschlag klingt sinnvoll, lass uns das ausprobieren.",
    #      "Your proposal sounds reasonable, let's try it out."),
    # ]},
]
