/* No network, dependencies or API keys. Interactive examples illustrate backend rules. */
function calculateAssessment(scores, finalWork, usedHelp) {
  if (!scores.length || scores.some(score => !Number.isInteger(score) || score < 0 || score > 2)) {
    throw new RangeError('Scores must be integers from 0 to 2');
  }
  const total = scores.reduce((sum, score) => sum + score, 0);
  const max = 2 * scores.length;
  const score = total / max;
  return { total, max, score, passed:score >= 0.8 && !(finalWork && usedHelp) };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { calculateAssessment };
}

if (typeof document !== 'undefined') {
  (() => {
    const deck = JSON.parse(document.getElementById('deck-data').textContent);
    const sections = [...document.querySelectorAll('section[data-slide]')];
    const contents = document.getElementById('contents-dialog');
    const notes = document.getElementById('speaker-notes');
    const live = document.getElementById('live-status');
    const list = document.getElementById('contents-list');
    const scores = [2,1,0,1];
    let finalWork = false;
    let usedHelp = false;
    let current = 0;
    let archStep = -1;
    const arch = [
      ['user','1. Ученик отправляет сообщение в Telegram.'],
      ['telegram','2. aiogram передаёт личное сообщение в учебный workflow.'],
      ['mcp','3. Backend получает состояние и материалы через MCP.'],
      ['model','4. GPT-6 Luna возвращает структурированный ответ.'],
      ['engine','5. Код проверяет результат и правило перехода.'],
      ['data','6. MCP сохраняет данные с проверкой revision.'],
      ['telegram','7. Ученик получает занятие или обратную связь в чате.'],
    ];

    deck.forEach((slide,index) => {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.textContent = slide.title;
      button.addEventListener('click',() => { show(index); contents.close(); });
      item.append(button); list.append(item);
    });

    function renderNotes() {
      const slide = deck[current];
      document.getElementById('notes-title').textContent = slide.title;
      document.getElementById('notes-time').textContent = `Слайд ${current+1} · ориентир ${slide.seconds} сек`;
      document.getElementById('notes-text').textContent = slide.notes;
      const sources = document.getElementById('notes-sources');
      sources.replaceChildren();
      slide.sources.forEach(source => {
        const item = document.createElement('li');
        const link = document.createElement('a');
        link.textContent = source.label;
        link.href = source.href;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        item.append(link); sources.append(item);
      });
    }

    function show(index, updateHash=true) {
      current = Math.max(0,Math.min(sections.length-1,index));
      sections.forEach((section,i) => { section.hidden = i !== current; });
      document.getElementById('counter').textContent = `${current+1} / ${sections.length}`;
      document.getElementById('chapter-label').textContent = deck[current].chapter;
      document.getElementById('deck-progress').style.width = `${(current+1)/sections.length*100}%`;
      document.getElementById('previous').disabled = current === 0;
      document.getElementById('next').disabled = current === sections.length-1;
      [...list.querySelectorAll('button')].forEach((button,i) => {
        if (i === current) button.setAttribute('aria-current','page');
        else button.removeAttribute('aria-current');
      });
      renderNotes();
      live.textContent = `Слайд ${current+1}: ${deck[current].title}`;
      if (updateHash) history.replaceState(null,'',`#slide-${current+1}`);
    }

    function fromHash() {
      const match = location.hash.match(/^#slide-(\d+)$/);
      const index = match ? Number(match[1])-1 : 0;
      show(index,false);
    }

    function toggleNotes(force) {
      notes.hidden = typeof force === 'boolean' ? !force : !notes.hidden;
      document.getElementById('notes-toggle').setAttribute('aria-expanded',String(!notes.hidden));
    }

    function updateAssessment() {
      const result = calculateAssessment(scores,finalWork,usedHelp);
      document.querySelectorAll('.score-choice').forEach(choice => {
        const selected = scores[Number(choice.getAttribute('data-score-row'))] === Number(choice.getAttribute('data-score-value'));
        choice.setAttribute('aria-pressed',String(selected));
        choice.querySelector('rect').setAttribute('fill',selected ? '#c4ef82' : '#1b2a30');
        choice.querySelector('text').setAttribute('fill',selected ? '#121b20' : '#f3f1e9');
      });
      const color = result.passed ? '#c4ef82' : '#ffc58d';
      const value = document.getElementById('score-value');
      value.textContent = new Intl.NumberFormat('ru-RU',{style:'percent',maximumFractionDigits:1}).format(result.score);
      value.setAttribute('fill',color);
      const status = document.getElementById('score-status');
      status.textContent = result.passed ? 'Переход к следующему этапу' : 'Дополнительная практика';
      status.setAttribute('fill',color);
      document.getElementById('score-reason').textContent = finalWork && usedHelp
        ? 'Для финала нужно решение без помощи'
        : `${result.total} из ${result.max} баллов, порог — 80%`;
      live.textContent = `${value.textContent}. ${status.textContent}.`;
    }

    function activateControl(element) {
      if (element.hasAttribute('data-score-row')) {
        scores[Number(element.getAttribute('data-score-row'))] = Number(element.getAttribute('data-score-value'));
        updateAssessment();
      } else if (element.hasAttribute('data-toggle')) {
        if (element.getAttribute('data-toggle') === 'final') finalWork = !finalWork;
        else usedHelp = !usedHelp;
        element.setAttribute('aria-pressed',String(element.getAttribute('data-toggle') === 'final' ? finalWork : usedHelp));
        updateAssessment();
      } else if (element.hasAttribute('data-arch-next')) {
        archStep = (archStep+1)%arch.length;
        document.querySelectorAll('.arch-node').forEach(node => node.classList.remove('active'));
        document.getElementById(`arch-${arch[archStep][0]}`).classList.add('active');
        document.getElementById('arch-description').textContent = arch[archStep][1];
        live.textContent = arch[archStep][1];
      }
    }

    document.querySelectorAll('svg [role="button"]').forEach(element => {
      element.addEventListener('click',() => activateControl(element));
      element.addEventListener('keydown',event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault(); activateControl(element);
        }
      });
    });
    document.getElementById('previous').addEventListener('click',() => show(current-1));
    document.getElementById('next').addEventListener('click',() => show(current+1));
    document.getElementById('notes-toggle').addEventListener('click',() => toggleNotes());
    document.getElementById('notes-close').addEventListener('click',() => toggleNotes(false));
    document.getElementById('contents-open').addEventListener('click',() => contents.showModal());
    document.getElementById('contents-close').addEventListener('click',() => contents.close());
    document.getElementById('fullscreen').addEventListener('click',async () => {
      try {
        if (document.fullscreenElement) await document.exitFullscreen();
        else await document.documentElement.requestFullscreen();
      } catch { live.textContent = 'Полноэкранный режим недоступен в этом окне.'; }
    });
    document.addEventListener('keydown',event => {
      if (['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName.toUpperCase()) || event.altKey || event.ctrlKey || event.metaKey) return;
      if (contents.open) return;
      if (['ArrowRight','PageDown'].includes(event.key)) { event.preventDefault(); show(current+1); }
      if (['ArrowLeft','PageUp'].includes(event.key)) { event.preventDefault(); show(current-1); }
      if (event.key === 'Home') { event.preventDefault(); show(0); }
      if (event.key === 'End') { event.preventDefault(); show(sections.length-1); }
      if (event.key.toLowerCase() === 'n') toggleNotes();
      if (event.key.toLowerCase() === 'g') contents.showModal();
      if (event.key.toLowerCase() === 'f') document.getElementById('fullscreen').click();
      if (event.key === 'Escape') toggleNotes(false);
    });
    window.addEventListener('hashchange',fromHash);
    fromHash();
    updateAssessment();
  })();
}
