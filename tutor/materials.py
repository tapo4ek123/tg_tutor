"""Small curated catalogue: no invented links or external page execution."""

MATERIALS = [
    {"title": "A Tour of Go", "url": "https://go.dev/tour/", "tags": "go голанг го golang"},
    {
        "title": "Effective Go",
        "url": "https://go.dev/doc/effective_go",
        "tags": "go голанг го golang",
    },
    {
        "title": "Go: создание модуля",
        "url": "https://go.dev/doc/tutorial/create-module",
        "tags": "go голанг го golang",
    },
    {
        "title": "Android: первый проект",
        "url": "https://developer.android.com/courses/android-basics-compose/course",
        "tags": "android андроид kotlin котлин",
    },
    {
        "title": "Spinning Up in Deep RL",
        "url": "https://spinningup.openai.com/en/latest/",
        "tags": "rl reinforcement обучение подкреплением",
    },
    {
        "title": "British Council LearnEnglish",
        "url": "https://learnenglish.britishcouncil.org/",
        "tags": "english английский английского",
    },
    {
        "title": "Instituto Cervantes: AVE",
        "url": "https://ave.cervantes.es/",
        "tags": "spanish испанский испанского español",
    },
]


def search_materials(query: str) -> list[dict]:
    words = set(query.lower().replace(",", " ").split())
    return [
        {"title": item["title"], "url": item["url"]}
        for item in MATERIALS
        if words.intersection(item["tags"].split())
    ][:3]
