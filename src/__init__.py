ADULT_CAT = [
        "Aktive Turner",
        "Aktive Turnerin",
        "Passivmitglied",
        "Freimitg. Turnend (1)",
        "Freimitg. nturnend (10)",
        "Ehrenmitg. nturnend",
        "Ehrenmitg. turnend",
    ]

JUGEND_CAT = ["Mädchen", "Knaben", "Kitu (Kinder)"]

EHRENMITGLIEDER_CAT = [
        "Ehrenmitg. nturnend",
        "Ehrenmitg. turnend",
    ]
NOT_ACTIVE_ERW_CAT = [
                "Passivmitglied",
                "Freimitg. nturnend (10)",
                "Ehrenmitg. nturnend"]

MALE = "Männlich"
FEMALE = "Weiblich"

def is_jugend_riege(riege:str)-> bool:
    jugend_strings = ["Meitliriege", "Knaben", "Jugi", "Kids", "Jugend", "klein", "Mädchen", "Elki", "Kitu"]
    for string in jugend_strings:
        if string in riege:
            return True
    return False