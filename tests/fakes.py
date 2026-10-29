"""Deterministic fixtures, NOT an AI model or a measure of teaching quality."""

from tutor.models import CriterionScore, Diagnostic, Grade, Lesson, Module, Plan


def lesson_fixture() -> Lesson:
    return Lesson(
        title="Go: обработка ошибок",
        explanation="Функция может вернуть значение и error. Сначала проверьте ошибку.",
        example='n, err := strconv.Atoi("42")\nif err != nil { return err }\nfmt.Println(n)',
        task="Объясните, как проверить err и почему результат нельзя использовать до проверки.",
        rubric=["Проверяет err != nil", "Обрабатывает ошибку до использования результата"],
        reference_answer="if err != nil { return err }; результат используется после проверки",
        hints=[
            "Посмотрите второе возвращаемое значение.",
            "Сравните err с nil.",
            "При ошибке верните её до работы с результатом.",
        ],
    )


class FakeTutor:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.bad_rubric = False

    async def generate(self, kind, schema, payload):
        self.calls.append((kind, payload))
        if self.fail:
            raise RuntimeError("fixture failure")
        if kind == "diagnostic":
            result = Diagnostic(
                introduction="Проверим исходный уровень.",
                questions=["Что такое nil?", "Как функция Go возвращает ошибку?"],
            )
        elif kind == "plan":
            result = Plan(
                goal="Написать CLI на Go с обработкой ошибок",
                diagnostic_feedback="Нужно закрепить ошибки.",
                feasibility_note="Три небольших занятия; сложность уточним по практике.",
                modules=[
                    Module(
                        title=title,
                        outcome="Самостоятельно обработать ошибку",
                        minutes=15,
                        success_criteria=["Проверка err до использования результата"],
                    )
                    for title in ["Основы Go", "Ошибки", "Итоговая CLI-программа"]
                ],
                final_challenge="Написать CLI, обрабатывающую неверный ввод.",
            )
        elif kind == "lesson":
            result = lesson_fixture()
            if payload["focus"]:
                result.task = "Повторная практика: " + result.task
        elif kind == "grade":
            score = 2 if "err != nil" in payload["answer"] and "return" in payload["answer"] else 0
            criteria = payload["lesson"]["rubric"]
            if self.bad_rubric:
                criteria = ["Модель подменила критерий", *criteria[1:]]
            result = Grade(
                criteria=[
                    CriterionScore(criterion=c, score=score, explanation="Fixture score")
                    for c in criteria
                ],
                feedback="Проверка завершена.",
                gaps=[] if score else ["Проверка ошибки до использования результата"],
            )
        elif kind == "ask":
            return schema(text="error сообщает, почему операция завершилась неуспешно.")
        else:
            raise AssertionError(kind)
        assert isinstance(result, schema)
        return result
