// Standalone HTML deck. Native SVG keeps the requested technical diagrams editable.
// Run: node scripts/build_presentation.mjs (no npm packages or network required).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const C = { bg:'#121b20', fg:'#f3f1e9', muted:'#a6b4ba', lime:'#c4ef82', line:'#415259', node:'#1b2a30', orange:'#ffc58d', blue:'#a3d6f7' };
const esc = value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
function text(x,y,value,size=26,color=C.fg,{weight=400,anchor='start',mono=false,leading=1.35}={}) {
  return String(value).split('\n').map((line,i)=>`<text x="${x}" y="${y+i*size*leading}" fill="${color}" font-size="${size}" font-weight="${weight}" text-anchor="${anchor}"${mono?' font-family="monospace"':''}>${esc(line)}</text>`).join('');
}
let number = 0;
function connector(points,{color=C.muted,dash=false,arrow=true}={}) {
  return `<path d="${points}" fill="none" stroke="${color}" stroke-width="2"${dash?' stroke-dasharray="7 6"':''}${arrow?` marker-end="url(#arrow-${number})"`:''}/>`;
}
function node(x,y,w,h,title,subtitle='',accent=false) {
  return `<g><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="10" fill="${C.node}" stroke="${accent?C.lime:C.line}" stroke-width="${accent?2:1}"/>${text(x+w/2,y+35,title,22,accent?C.lime:C.fg,{anchor:'middle',weight:500})}${subtitle?text(x+w/2,y+h-20,subtitle,17,C.muted,{anchor:'middle'}):''}</g>`;
}
function rule(y=630) { return `<path d="M72 ${y} H1208" stroke="${C.line}"/>`; }
function small(x,y,t) { return text(x,y,t,19,C.muted); }
function heading(chapter,title) { chapter=chapter.replace(/^\d+\s*\/\s*/,`${String(number-1).padStart(2,'0')} / `); return text(72,57,chapter,15,C.lime,{weight:500})+text(72,119,title,48,C.fg,{weight:500}); }
function annotation(t) { return rule()+small(72,667,t); }
const slides=[];
function add(title,chapter,seconds,notes,sources,draw) {
  number=slides.length+1;
  const content=draw();
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720" role="${content.includes('role="button"')?'group':'img'}" aria-labelledby="title-${number} desc-${number}" font-family="Arial, sans-serif"><title id="title-${number}">${esc(title)}</title><desc id="desc-${number}">${esc(notes)}</desc><defs><marker id="arrow-${number}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="${C.muted}"/></marker></defs><rect width="1280" height="720" fill="${C.bg}"/>${content}</svg>`;
  slides.push({id:number,title,chapter,seconds,notes,sources,svg});
}
const code=(label,href)=>({label,href:`../${href}`});

add('SkillPilot: AI-тьютор в Telegram','Проект',20,
  'Представить проект как помощника для самостоятельного обучения. Он собирает исходные данные, даёт практику, оценивает ответы и сохраняет учебный маршрут. Главная демонстрация — ошибка ученика, которая меняет следующее упражнение. Презентация занимает примерно 7–8 минут, после неё остаётся время на живой показ.',
  [code('README','README.md'),code('Спецификация','docs/spec.md')],()=>
  text(72,70,'УЧЕБНЫЙ ПРОЕКТ / 2026',16,C.lime)+
  text(72,245,'SkillPilot',104,C.fg,{weight:600})+
  text(76,326,'AI-тьютор в Telegram',48,C.fg)+
  text(76,419,'Персональный план и практика\nс учётом результатов ученика',30,C.muted)+
  rule(550)+text(76,596,'GPT-6 Luna',24,C.lime)+text(380,596,'MCP',24,C.lime)+
  text(586,596,'Память обучения',24,C.lime)+text(950,596,'Напоминания',24,C.lime));

add('Задача и пользователь','Сценарий',30,
  'Пользователь уже мотивирован учиться, но не уверен в последовательности тем и достаточности своей практики. На примере Go цель формулируется через наблюдаемый результат — CLI-программу с корректной обработкой ввода. Это пример постановки цели, а не обещание, что любой навык можно освоить за три занятия.',
  [code('Постановка задачи','docs/spec.md'),code('Сбор профиля','tutor/engine.py')],()=>
  heading('01 / ЗАДАЧА','Самостоятельное обучение')+
  `<path d="M74 187 V404" stroke="${C.lime}" stroke-width="3"/>`+
  text(104,220,'«Знаю Python. Хочу освоить Go',38,C.fg)+
  text(104,274,'и написать первую CLI-программу.',38,C.fg)+
  text(104,328,'Есть 30 минут три раза в неделю».',38,C.fg)+
  text(76,466,'Потребность',18,C.lime)+text(76,510,'Выбрать следующий шаг\nи увидеть свои пробелы',27)+
  text(690,466,'Ожидаемый результат',18,C.lime)+text(690,510,'Выполнить итоговую работу\nпо понятным критериям',27)+
  annotation('Несколько навыков параллельно. У каждого свой план, занятия и прогресс.'));

add('Пользовательский путь','Учебный цикл',25,
  'Показать весь путь в Telegram. Цель, опыт, бюджет времени и срок вводятся последовательно. Модель создаёт диагностику, затем план. Пользователь подтверждает план, выполняет задания и видит прогресс. Напоминания включаются отдельно по желанию пользователя.',
  [code('Машина состояний','tutor/engine.py'),code('LearningState','tutor/models.py')],()=>{
    let s=heading('02 / УЧЕБНЫЙ ЦИКЛ','Путь ученика в Telegram');
    const boxes=[[72,185,'Выбор навыка','Свой профиль и цель'],[480,185,'Диагностика','2–4 вопроса'],[888,185,'План','3–6 этапов'],[888,388,'Занятие','Объяснение и практика'],[480,388,'Проверка','Рубрика и обратная связь'],[72,388,'Следующий шаг','Переход или повторение']];
    boxes.forEach(([x,y,t,sub])=>s+=node(x,y,320,120,t,sub));
    s+=connector('M392 245 H476')+connector('M800 245 H884')+connector('M1048 305 V384')+
      connector('M888 448 H804')+connector('M480 448 H396')+
      connector('M232 508 V562 H1048 V512',{dash:true});
    s+=small(475,591,'Практика продолжается до итоговой работы');
    return s+annotation('План требует подтверждения. Прогресс и текущее задание сохраняются между сессиями.');
  });

add('Несколько навыков параллельно','Учебный цикл',30,
  'Пользователь добавляет навыки командой /newskill, видит список через /skills и выбирает нужный кнопкой или /switch ID. В каждый момент обычное сообщение относится к выбранному навыку, но остальные продолжают храниться. У каждого своя диагностика, план, задание, подсказки, попытки и пауза по лимиту. Переключение обратно восстанавливает то же незавершённое задание. Завершённые навыки остаются в списке с отметкой. Числа на схеме иллюстративны, это не реальные результаты ученика.',
  [code('Команды навыков','tutor/engine.py'),code('Хранение и выбор','tutor/storage.py'),code('Кнопки Telegram','tutor/telegram.py')],()=>
  heading('03 / НАВЫКИ','Несколько направлений, отдельные маршруты')+
  node(72,184,340,94,'Go','Выбран в диалоге',true)+
  node(72,333,340,94,'Испанский','Сохранённое занятие')+
  node(72,482,340,94,'Reinforcement Learning','Свой план и прогресс')+
  connector('M412 231 H570')+
  node(578,184,630,320,'Независимая учебная сессия','Данные остальных навыков сохраняются')+
  text(620,295,'Диагностика и план\nТекущее задание\nИстория ответов и подсказок\nПрогресс и пробелы',26,C.fg,{leading:1.5})+
  text(578,567,'/skills  /newskill  /switch ID',26,C.lime,{mono:true})+
  annotation('При возвращении к навыку бот продолжает с того места, где остановился ученик.'));

add('Построение учебного плана','Учебная логика',40,
  'План появляется после ответа ученика на диагностику. Модель получает цель, опыт, минуты на сессию, частоту, срок, диагностические вопросы и ответ. Plan содержит диагностическую обратную связь, оценку реалистичности, этапы и итоговую работу. Каждый Module хранит ожидаемый результат, длительность и критерии успеха. Код ограничивает число этапов и отклоняет план, где занятие превышает бюджет. Связность и педагогическую обоснованность последовательности задаёт инструкция модели, а не отдельный алгоритм графа зависимостей.',
  [code('Генерация plan','tutor/llm.py'),code('Проверка бюджета','tutor/engine.py'),code('Plan и Module','tutor/models.py')],()=>
  heading('03 / ПЛАН','Профиль и диагностика задают маршрут')+
  node(72,183,288,132,'Профиль ученика','Цель, опыт, время, срок')+
  node(72,362,288,118,'Ответы диагностики','Что уже получается')+
  connector('M360 249 H422 V319 H474')+connector('M360 421 H422 V319 H474')+
  node(480,257,250,124,'GPT-6 Luna','Режим plan',true)+connector('M730 319 H790')+
  text(820,196,'УЧЕБНЫЙ ПЛАН',17,C.lime)+
  text(820,240,'Результат этапа',27)+text(820,286,'Время занятия',27)+
  text(820,332,'Скрытые критерии',27)+text(820,378,'Итоговая работа',27)+
  `<path d="M804 213 V396" stroke="${C.line}" stroke-width="2"/>`+
  text(76,550,'Код проверяет структуру и длительность.',26,C.lime)+
  small(76,587,'Модель обосновывает последовательность тем и реалистичность срока.')+
  annotation('Число этапов: 3–6. Последний этап по инструкции — самостоятельная итоговая работа.'));

add('Построение занятия','Учебная логика',35,
  'Перед генерацией занятия backend читает сохранённое состояние и получает материалы через MCP. В контекст LLM входят профиль, весь план, текущий этап, фокус на пробелах и последние три попытки. Lesson содержит объяснение, другой пример, практическое задание, рубрику, эталон и три подсказки. Ученик видит объяснение, пример и задание. Рубрика и эталон остаются внутри проверки; отдельные баллы по критериям не выводятся. Эталон не выводится в чат, подсказки показываются по запросу. Ограничения длины текста и отличие примера от задания заданы в промпте. Показанная структура иллюстративна, она не является результатом живого вызова модели.',
  [code('Сбор контекста lesson','tutor/engine.py'),code('Lesson','tutor/models.py'),code('Инструкция занятия','tutor/llm.py')],()=>
  heading('04 / ЗАНЯТИЕ','Контекст определяет практику')+
  text(76,192,'КОНТЕКСТ МОДЕЛИ',17,C.lime)+
  text(76,240,'Профиль и текущий этап\nПлан обучения\nПробелы ученика\nПоследние 3 попытки\nСсылки из каталога MCP',26,C.fg,{leading:1.6})+
  connector('M414 327 H492')+node(500,271,220,118,'LLM','Режим lesson',true)+connector('M720 327 H790')+
  text(820,192,'СТРУКТУРА ЗАНЯТИЯ',17,C.lime)+
  text(820,240,'Объяснение\nПример\nЗадание',27,C.fg,{leading:1.5})+
  text(820,442,'Рубрика и эталон скрыты',23,C.orange)+
  small(820,482,'Подсказки доступны по запросу')
);

// Add the lower annotation separately to keep the lesson diagram uncluttered.
slides.at(-1).svg=slides.at(-1).svg.replace('</svg>',annotation('Одна сессия строится вокруг одного задания. /hint и /ask дают дополнительную помощь.')+'</svg>');

add('Проверка ответа','Оценивание',40,
  'На слайде симулятор логики приложения с четырьмя примерными критериями Go. Нажатие 0, 1 или 2 меняет оценку критерия. Код делит сумму баллов на максимально возможную сумму и сравнивает с 80%. При четырёх критериях баллы дискретные: 6 из 8 = 75% не проходит, 7 из 8 = 87,5% проходит. Финал с любой помощью не засчитывается даже при максимальном балле. Эти интерактивные оценки задаёт докладчик, а не LLM. В настоящем сервисе модель оценивает критерии, а код требует точного совпадения списка с сохранённой рубрикой.',
  [code('grade_score и passed','tutor/engine.py'),code('Grade','tutor/models.py'),code('Инструкция grade','tutor/llm.py')],()=>{
    let s=heading('05 / ПРОВЕРКА','Рубрика и правило перехода');
    s+=small(76,169,'Служебная рубрика: ученик её не видит. Пример работает без вызова модели.');
    const labels=['Проверка err != nil','Выход при ошибке','Работа с результатом','Объяснение решения'];
    const scores=[2,1,0,1];
    labels.forEach((label,row)=>{
      const y=220+row*67;
      s+=text(76,y+12,label,24);
      for(let value=0;value<=2;value++){
        const x=452+value*68;
        s+=`<g class="choice score-choice" role="button" tabindex="0" aria-label="${esc(label)}: ${value} из 2" aria-pressed="${scores[row]===value}" data-score-row="${row}" data-score-value="${value}"><rect x="${x}" y="${y-18}" width="52" height="44" rx="6" fill="${scores[row]===value?C.lime:C.node}" stroke="${C.line}"/><text x="${x+26}" y="${y+12}" text-anchor="middle" font-size="22" fill="${scores[row]===value?C.bg:C.fg}">${value}</text></g>`;
      }
    });
    s+=`<path d="M698 200 V553" stroke="${C.line}"/>`+
      text(755,228,'Сумма / (2 × число критериев)',23,C.muted)+
      `<text id="score-value" x="755" y="322" fill="${C.orange}" font-size="78">50%</text>`+
      `<text id="score-status" x="755" y="373" fill="${C.orange}" font-size="28">Дополнительная практика</text>`+
      `<text id="score-reason" x="755" y="412" fill="${C.muted}" font-size="21">4 из 8 баллов, порог — 80%</text>`;
    [['final','Итоговая работа',76,540],['help','Была помощь',367,540]].forEach(([id,label,x,y])=>{
      s+=`<g class="choice toggle-choice" role="button" tabindex="0" aria-pressed="false" aria-label="${label}" data-toggle="${id}"><rect x="${x}" y="${y-24}" width="260" height="50" rx="6" fill="${C.node}" stroke="${C.line}"/>${text(x+20,y+9,label,21)}</g>`;
    });
    return s+annotation('Ученик видит общую оценку и объяснение ошибок. Рубрика остаётся внутри проверки.');
  });

add('Адаптация обучения','Учебная логика',35,
  'При ошибке backend сохраняет Attempt, список gaps и запись в adaptations. Текущий индекс этапа остаётся прежним, старое задание освобождается, а новое получает фокус на пробелах. План в MVP корректируется добавлением целевой практики. Перестроение порядка всех тем и интервальное повторение оставлены для следующей версии. Успешный ответ переводит к следующему этапу. Если это последняя работа и помощь не использовалась, состояние становится done.',
  [code('Ветка passed / gaps','tutor/engine.py'),code('Attempt и LearningState','tutor/models.py')],()=>
  heading('06 / АДАПТАЦИЯ','Результат проверки меняет следующий шаг')+
  node(430,177,420,92,'Ответ оценён','Рубрика сохранена')+
  connector('M534 269 V315 H258 V350')+connector('M746 269 V315 H1020 V350')+
  text(267,300,'Балл ниже 80% или финал с помощью',19,C.orange,{anchor:'middle'})+
  text(1013,300,'Условие прохождения выполнено',19,C.lime,{anchor:'middle'})+
  node(72,356,390,111,'Сохранить пробелы','gaps → focus')+
  node(818,356,390,111,'Перейти к следующему этапу','module_index + 1',true)+
  connector('M267 467 V506')+connector('M1013 467 V506')+
  text(76,548,'Новое задание на том же этапе\nс учётом последней ошибки',26)+
  text(823,548,'После итоговой работы:\nцель выполнена по плану',26)+
  annotation('MVP адаптирует практику. Полное перестроение программы — следующая итерация.'));

add('Техническая архитектура','Техническое описание',40,
  'Пользователь общается с Telegram. aiogram получает сообщения через long polling. Учебный workflow вызывает Responses API GPT-6 Luna и инструменты MCP. MCP работает отдельным дочерним процессом через stdio и обращается к SQLite и локальному каталогу материалов. Планировщик — фоновая задача в основном процессе; он получает расписание через MCP и отправляет сообщения через Bot API. Кнопка на слайде подсвечивает последовательность обращения, это схема архитектуры, а не сетевой запрос.',
  [code('Запуск процессов','tutor/main.py'),code('MCP client','tutor/mcp_client.py'),code('Telegram','tutor/telegram.py')],()=>{
    let s=heading('07 / АРХИТЕКТУРА','Telegram, учебный workflow и MCP');
    const parts=[
      [72,213,200,108,'Ученик','Telegram','user'],
      [337,213,240,108,'aiogram','Long polling','telegram'],
      [642,213,280,108,'Учебный workflow','Переходы и валидация','engine'],
      [642,422,280,108,'Learning MCP','Отдельный subprocess','mcp'],
      [992,213,216,108,'GPT-6 Luna','Responses API','model'],
      [992,422,216,108,'Данные','SQLite + каталог','data'],
    ];
    parts.forEach(([x,y,w,h,t,sub,id])=>s+=`<g id="arch-${id}" class="arch-node">${node(x,y,w,h,t,sub,id==='engine')}</g>`);
    s+=connector('M272 267 H333')+connector('M577 267 H638')+
      connector('M922 267 H988')+connector('M782 321 V418')+
      connector('M922 476 H988')+
      text(790,376,'stdio',17,C.muted)+
      text(76,435,'Планировщик напоминаний',24,C.lime)+
      small(76,475,'Читает расписание через MCP');
    return s;
  });
slides.at(-1).svg=slides.at(-1).svg.replace('</svg>',
  small(76,510,'Отправляет сообщения через Bot API')+
  `<g role="button" tabindex="0" class="choice" data-arch-next="true" aria-label="Показать следующий шаг сценария"><rect x="72" y="563" width="236" height="42" rx="6" fill="${C.node}" stroke="${C.line}"/>${text(92,591,'Показать сценарий',20,C.lime)}</g>`+
  `<text id="arch-description" x="337" y="590" fill="${C.muted}" font-size="18">Нажмите кнопку, чтобы пройти путь запроса</text>`+
  annotation('Учебные данные доступны через MCP. Расход модели хранится в отдельном ledger бюджета.')+'</svg>');

add('MCP: назначение и инструменты','Техническое описание',35,
  'MCP — Model Context Protocol, интерфейс между приложением и сервером инструментов. В проекте используется официальный Python SDK и транспорт stdio. Backend выступает MCP-клиентом и вызывает tools/list и tools/call. Сервер предоставляет управление навыками, учебным состоянием, материалами и расписанием. Это отдельный приватный процесс. Решение, какой инструмент вызвать, принимает учебный workflow, а не LLM. User ID берётся из Telegram; switch_skill проверяет принадлежность навыка. Если сервер выносить в сеть, потребуется отдельная аутентификация.',
  [code('MCP server: инструменты','tutor/mcp_server.py'),code('MCP client','tutor/mcp_client.py'),{label:'Официальный MCP Python SDK',href:'https://github.com/modelcontextprotocol/python-sdk'}],()=>
  heading('08 / MCP','Единый интерфейс к учебным данным')+
  node(72,184,280,105,'Backend','MCP client')+
  node(465,184,350,105,'Learning MCP Server','Инструменты и валидация',true)+
  node(928,184,280,105,'Данные','SQLite и каталог')+
  connector('M352 236 H461')+connector('M815 236 H924')+
  small(365,218,'stdio')+
  text(76,370,'Управление навыками',25,C.lime)+
  text(76,421,'list_skills\ncreate_skill\nswitch_skill',24,C.fg,{mono:true,leading:1.65})+
  text(640,370,'Учебные данные и материалы',25,C.lime)+
  text(640,421,'get_learning_state\nsave_learning_state\nsearch_materials',24,C.fg,{mono:true,leading:1.65})+
  annotation('User ID задаёт приложение. MCP проверяет владельца навыка и версию выбранной сессии.'));

add('MCP: сквозной сценарий','Техническое описание',35,
  'Разобрать /lesson как реальный сквозной сценарий. Backend сначала запрашивает состояние, затем материалы. Эти вызовы выполняются через официальный MCP Python SDK, с initialize и tools/call. Далее модель создаёт структурированный Lesson. После проверки Pydantic backend вызывает save_learning_state с ожидаемой revision. Только после успешной записи ученик получает занятие. MCP не вызывается моделью автономно: последовательность определяет код. Приватный stdio-сервер не имеет сетевой авторизации и не должен напрямую публиковаться наружу.',
  [code('Протокол MCP','tutor/mcp_client.py'),code('Инструменты','tutor/mcp_server.py'),code('/lesson','tutor/engine.py')],()=>{
    let s=heading('08 / MCP','Что происходит после /lesson');
    const xs=[140,480,830,1140], titles=['Telegram','Backend','MCP','LLM'];
    xs.forEach((x,i)=>{s+=text(x,181,titles[i],21,i===2?C.lime:C.fg,{anchor:'middle'});s+=connector(`M${x} 202 V574`,{arrow:false,color:C.line,dash:true});});
    const rows=[
      [140,480,236,'1. /lesson'],
      [480,830,294,'2. get_learning_state'],
      [480,830,352,'3. search_materials'],
      [480,1140,410,'4. generate → Lesson'],
      [480,830,468,'5. save_learning_state + revision'],
      [480,140,526,'6. Занятие в чате'],
    ];
    rows.forEach(([x1,x2,y,label],i)=>{
      s+=connector(`M${x1} ${y} H${x2}`);
      s+=text(Math.min(x1,x2)+14,y-10,label,18);
      if(i>0 && i<5) s+=connector(`M${x2} ${y+18} H${x1}`,{dash:true});
    });
    return s+annotation('Сплошные линии — запросы, пунктир — ответы. Код валидирует и сохраняет занятие до выдачи.');
  });

add('Память и согласованность','Техническое описание',25,
  'Учебная база содержит learners, skills и reminders. learners хранит общую revision и active_skill_id. skills хранит отдельный JSON-снимок каждого навыка, связанный с user_id. Переключение меняет только указатель и revision, сохраняя незавершённые задания. Старая одноцелевая база автоматически переносится в первый навык в транзакции. Напоминания общие на пользователя. Расход модели хранится отдельно в budget.sqlite3. Проверка ownership исключает доступ к чужому навыку, а общая revision отклоняет кнопки от прежнего выбора.',
  [code('Миграция и навыки','tutor/storage.py'),code('Состояние навыка','tutor/models.py'),code('Ledger расхода','tutor/budget.py')],()=>
  heading('09 / ДАННЫЕ','Каждый навык хранит свой прогресс')+
  text(76,210,'learners',29,C.lime,{mono:true})+
  text(76,280,'user_id\nrevision\nactive_skill_id',23,C.fg,{mono:true,leading:1.9})+
  text(470,210,'skills',29,C.lime,{mono:true})+
  text(470,280,'skill_id, user_id\nstate (JSON)',23,C.fg,{mono:true,leading:1.9})+
  text(470,390,'План, задание, ответы,\nподсказки и пробелы',23,C.muted)+
  text(910,210,'reminders',29,C.lime,{mono:true})+
  text(910,280,'user_id\nРасписание\nnext_due + lease',22,C.fg,{leading:1.9})+
  connector('M365 200 H440')+
  rule(475)+text(76,521,'Переключение навыка меняет общую revision.',28)+
  text(76,568,'Старая кнопка не сможет отправить ответ в другой навык.',25,C.muted)+
  annotation('При обновлении существующая цель и незавершённое занятие переносятся в первый навык.'));

add('Напоминания','Техническое описание',30,
  'Уведомления не зависят от решения LLM. Пользователь выбирает время, часовой пояс и дни недели. Планировщик проверяет расписание с периодом 30 секунд. MCP выдаёт due-запись с lease на пять минут, бот отправляет сообщение и подтверждает доставку. 429 вызывает retry, блокировка бота отключает напоминания, сообщение предлагает выбрать один из незавершённых навыков, а завершение всех навыков прекращает отправку. Старые сообщения больше двух часов пропускаются. После падения между отправкой и подтверждением возможен дубль, поэтому строго exactly-once не заявляем.',
  [code('Планировщик','tutor/reminders.py'),code('Расписание и DST','tutor/scheduling.py'),code('Lease и подтверждение','tutor/storage.py')],()=>
  heading('10 / НАПОМИНАНИЯ','Расписание хранится отдельно от диалога')+
  text(76,186,'/remind 19:00 Europe/Moscow 1,3,5',28,C.lime,{mono:true})+
  node(72,247,250,110,'Расписание','Время, дни, timezone')+
  node(397,247,260,110,'SQLite через MCP','next_due + lease')+
  node(732,247,250,110,'Bot API','sendMessage')+
  connector('M322 302 H393')+connector('M657 302 H728')+
  connector('M857 357 V404 H527 V361',{dash:true})+
  small(580,434,'Подтверждение или повторная попытка')+
  text(76,504,'Управление ученика',19,C.lime)+text(76,546,'Выбрать навык\nПеренести или отключить',25)+
  text(720,504,'Работа сервера',19,C.lime)+text(720,546,'Проверка каждые 30 секунд\nСохранение после перезапуска',25)+
  annotation('При падении между отправкой и подтверждением возможен повтор уведомления.'));

add('Развёртывание и границы MVP','Готовность проекта',25,
  'Для эксплуатации предусмотрен один Docker-контейнер, постоянный named volume и исходящий HTTPS. Домен и входящий порт для long polling не нужны. Бот, фоновый планировщик и дочерний MCP запускаются на постоянном сервере. Подготовлены Dockerfile, Compose и CI, но развёртывание и сборка на целевом хосте требуют проверки. Доступ к модели подтверждён живой диагностикой и Eval от 28.10.2026: 19 из 20 оценок попали в ожидаемый диапазон. До защиты нужно проверить постоянный хостинг, опубликовать подготовленный репозиторий и продемонстрировать работающего бота. Ограничения MVP: текстовая проверка, отсутствие исполнения кода, одна модель для генерации и оценивания.',
  [code('Docker Compose','compose.yaml'),code('Dockerfile','Dockerfile'),code('SDD и задачи','docs/plan.md'),code('Спецификация','docs/spec.md')],()=>
  heading('12 / РАЗВЁРТЫВАНИЕ','Один сервис на постоянном сервере')+
  node(72,187,665,250,'Docker-контейнер','Telegram polling + workflow + scheduler + MCP',true)+
  text(110,300,'Python 3.12 / aiogram / Pydantic',25)+
  text(110,350,'OpenAI SDK / официальный MCP SDK',25)+
  small(110,391,'SDD: спецификация, план задач, проверки')+
  connector('M404 437 V492')+node(221,498,366,87,'Persistent volume','SQLite и heartbeat')+
  text(807,217,'ПОДГОТОВЛЕНО',17,C.lime)+
  text(807,259,'Код, тесты, Docker, CI\nREADME и live Eval',23)+
  text(807,373,'ДО ЗАЩИТЫ',17,C.orange)+
  text(807,416,'Проверка контейнера\nХостинг и живое демо\nПубличные ссылки',23,C.fg,{leading:1.6})+
  annotation('Несколько навыков. Текстовые задания, проверка кода без исполнения, общий бюджет $3/сутки.'));

// Export source diagrams separately only to private QA, never as runtime dependencies.
const qaDir=process.env.PRESENTATION_QA_DIR;
if(qaDir){fs.mkdirSync(qaDir,{recursive:true});slides.forEach(s=>fs.writeFileSync(path.join(qaDir,`slide-${String(s.id).padStart(2,'0')}.svg`),s.svg));}
const style=fs.readFileSync(path.join(root,'scripts/presentation.css'),'utf8');
const runtime=fs.readFileSync(path.join(root,'scripts/presentation_runtime.js'),'utf8');
const metadata=slides.map(({svg,...rest})=>rest);
const html=`<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="SkillPilot: устройство AI-тьютора, построение плана и занятий, MCP и проверка прогресса"><title>SkillPilot — AI-тьютор: презентация проекта</title><style>${style}</style></head>
<body><header class="toolbar"><a class="brand" href="#slide-1">Skill<span>Pilot</span></a><span class="subtitle">AI-тьютор в Telegram</span><div class="tools"><button id="contents-open" title="Оглавление (G)">Оглавление</button><button id="notes-toggle" aria-expanded="false" title="Заметки докладчика (N)">Заметки</button><button id="fullscreen" title="Полный экран (F)">Полный экран</button></div></header>
<main id="stage" aria-label="Презентация проекта">${slides.map(s=>`<section class="slide" id="slide-${s.id}" data-slide="${s.id}" aria-label="${s.id}. ${esc(s.title)}"${s.id===1?'':' hidden'}>${s.svg}</section>`).join('\n')}</main>
<footer class="navigation"><span id="chapter-label">Проект</span><div class="slide-progress" aria-hidden="true"><span id="deck-progress"></span></div><span id="counter" aria-live="polite">1 / ${slides.length}</span><button id="previous" aria-label="Предыдущий слайд">←</button><button id="next" aria-label="Следующий слайд">→</button><span class="keyhint">← → слайды · N заметки</span></footer>
<aside id="speaker-notes" hidden aria-label="Заметки докладчика"><button id="notes-close" aria-label="Закрыть заметки">×</button><p class="overline" id="notes-time"></p><h2 id="notes-title"></h2><p id="notes-text"></p><h3>Исходники и источники</h3><ul id="notes-sources"></ul></aside>
<dialog id="contents-dialog" aria-labelledby="contents-title"><div class="dialog-head"><h2 id="contents-title">Содержание</h2><button id="contents-close" aria-label="Закрыть оглавление">×</button></div><ol id="contents-list"></ol></dialog>
<p class="sr-only" id="live-status" aria-live="polite"></p><noscript><p class="no-script">Для переключения слайдов и интерактивных примеров включите JavaScript. Для печати доступны все слайды.</p></noscript>
<script id="deck-data" type="application/json">${JSON.stringify(metadata).replaceAll('<','\\u003c')}</script><script>${runtime}</script></body></html>`;
fs.writeFileSync(path.join(root,'docs/presentation.html'),html);
const notes=`# SkillPilot: заметки к защите\n\nПлан: примерно 7–8 минут на слайды и около 2 минут на живую демонстрацию.\n\nОткрыть [HTML-презентацию](presentation.html). Управление: ←/→, Home/End, G — оглавление, N — заметки, F — полный экран. Все схемы встроены, внешние библиотеки и интернет для просмотра не нужны.\n\n${metadata.map(s=>`## ${s.id}. ${s.title}\n\nОриентир: ${s.seconds} секунд.\n\n${s.notes}\n\nИсточники: ${s.sources.map(x=>`[${x.label}](${x.href})`).join(', ')}.\n`).join('\n')}`;
fs.writeFileSync(path.join(root,'docs/presentation-notes.md'),notes);
console.log(`Built ${slides.length} slides; planned slide talk: ${metadata.reduce((a,s)=>a+s.seconds,0)} seconds.`);
