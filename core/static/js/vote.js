/* ============================================================
   vote.js — гостевой поток «Тыквоголос» (Django-версия, этап 2).
   Перенос из статического прототипа (план бэкенда §9.3):
   - состояние и каталог приходят из server-rendered <script id="tg-bootstrap">
     (замена data.js/state.js — план бэкенда §7.3);
   - mockPostVote() заменён реальным fetch POST /api/v1/vote с заголовками
     X-CSRFToken и X-Voter-Token (FR-V-02); контракт ошибок прежний:
     200 ok / 409 already_voted|paused|not_active / 422 errors / 400 honeypot,
     плюс 429 rate_limited («Слишком часто — подождите минуту 🦇»);
   - черновик остаётся в localStorage (FR-V-07, переживает паузу E3);
   - токен гостя дублируется в localStorage для восстановления через
     X-Voter-Token, если cookie потеряна (FR-V-02).
   ============================================================ */
(function () {
    'use strict';

    /* ---------- server bootstrap (замена data.js + state.js) ---------- */
    var BG_NODE = document.getElementById('tg-bootstrap');
    var BG = BG_NODE ? JSON.parse(BG_NODE.textContent) : {};

    var D = {
        categories: BG.categories || [],
        participants: BG.participants || [],
        groups: BG.groups || [],
        findSubject: function (type, id) {
            var list = (type === 'group') ? D.groups : D.participants;
            for (var i = 0; i < list.length; i++) {
                if (String(list[i].id) === String(id)) return list[i];
            }
            return { id: id, number: '?', name: 'Неизвестный призрак', desc: '', photo: false };
        }
    };

    /* S — шим совместимости с прототипом: состояние/флаг voted — с сервера,
       черновик и токен — в localStorage (FR-V-07/FR-V-02). */
    var S = {
        KEYS: { draft: 'tykvogolos_draft', token: 'tykvogolos_token' },
        _voted: !!BG.voted,
        getState: function () { return BG.state || 'NOT_STARTED'; },
        isVoted: function () { return S._voted; },
        setVoted: function (b) { S._voted = !!b; },
        setVotersTotal: function (n) { BG.voters_total = n; },
        getVotersTotal: function () { return BG.voters_total || 0; },
        readJSON: function (key, def) {
            try {
                var v = localStorage.getItem(key);
                return v ? JSON.parse(v) : def;
            } catch (e) { return def; }
        },
        writeJSON: function (key, obj) {
            try { localStorage.setItem(key, JSON.stringify(obj)); } catch (e) { }
        },
        clearDraft: function () {
            try { localStorage.removeItem(S.KEYS.draft); } catch (e) { }
        }
    };

    var FX = window.TG_FX;

    var viewRoot = document.getElementById('view-root');
    var progressNav = document.getElementById('progress');
    var stateBadge = document.getElementById('state-badge');

    var NOM_CATS = D.categories.filter(function (c) { return c.id !== 'GRANDPRIX'; }); /* 4 номинации */
    var ALL_CATS = D.categories; /* 5 шагов в фиксированном порядке */

    var draft = { choices: {}, step: 1 };
    var confirmBusy = false;
    var autoTimer = 0;

    /* ---------- утилиты ---------- */

    function esc(s) {
        /* Экранирование HTML через charCode-маппинг (без raw-entities в коде) */
        var map = { 38: 'amp', 60: 'lt', 62: 'gt', 34: 'quot', 39: '#39' };
        return String(s).replace(/[&<>"']/g, function (c) {
            return '&' + map[c.charCodeAt(0)] + ';';
        });
    }

    function emptyChoices() {
        var o = {};
        ALL_CATS.forEach(function (c) { o[c.id] = null; });
        return o;
    }

    function hasAnyChoice() {
        return ALL_CATS.some(function (c) { return !!draft.choices[c.id]; });
    }

    /* Псевдонимный токен гостя (FR-V-02): localStorage-дубль для
       восстановления через X-Voter-Token при потере cookie */
    function token() {
        var t = null;
        try { t = localStorage.getItem(S.KEYS.token); } catch (e) { }
        if (!t) {
            t = (window.crypto && crypto.randomUUID)
                ? crypto.randomUUID()
                : 't-' + Date.now() + '-' + Math.random().toString(16).slice(2);
            try { localStorage.setItem(S.KEYS.token, t); } catch (e) { }
        }
        return t;
    }

    function focusHero() {
        var h = viewRoot.querySelector('.hero');
        if (h) h.focus({ preventScroll: true });
    }

    function saveDraft() {
        S.writeJSON(S.KEYS.draft, draft);
    }

    function loadDraft() {
        var saved = S.readJSON(S.KEYS.draft, null);
        if (saved && saved.choices && ALL_CATS.every(function (c) { return c.id in saved.choices; })) {
            draft = saved; /* FR-V-07: восстановление черновика */
        } else {
            draft = { choices: emptyChoices(), step: 1 };
        }
    }

    function subjectsFor(cat) {
        var p = D.participants;
        if (cat.subjects === 'groups') return D.groups;
        return p; /* гран-при: только участники (grandprix_includes_groups=False) */
    }

    /* ============================================================
       ПРАВИЛА ГОЛОСОВАНИЯ — изолированный блок (серверная копия —
       core/services/rules.py; тест №8 сверяет их поведение).

       FR-V-05: кандидат, выбранный в одной из 4 номинаций, блокируется
       в остальных трёх. FR-V-06: гран-при не конфликтует ни с чем.
       ============================================================ */
    function canVoteFor(catId, subjectType, subjectId) {
        if (catId === 'GRANDPRIX') return null;
        for (var i = 0; i < NOM_CATS.length; i++) {
            var c = NOM_CATS[i];
            if (c.id === catId) continue;
            var ch = draft.choices[c.id];
            if (ch && ch.type === subjectType && String(ch.id) === String(subjectId)) return c;
        }
        return null;
    }

    function buildPayload() {
        var votes = [];
        NOM_CATS.forEach(function (c) {
            var ch = draft.choices[c.id];
            if (ch) {
                votes.push({
                    category: c.id,
                    subject_type: ch.type === 'group' ? 'GROUP' : 'PARTICIPANT',
                    subject_id: ch.id
                });
            }
        });
        var gp = draft.choices.GRANDPRIX;
        return {
            token: token(),
            votes: votes,
            /* клиентская валидация: гран-при — только участник */
            grandprix: (gp && gp.type === 'participant')
                ? { subject_type: 'PARTICIPANT', subject_id: gp.id }
                : null,
            website: '' /* honeypot — клиент отправляет пустым (FR-V-08) */
        };
    }

    /* ============================================================
       POST /api/v1/vote — реальный fetch (план бэкенда §7.1, §9.3).
       Контракт: 200 {"status":"ok","voters_total":N}
                 409 {"error":"already_voted"|"not_active"|"paused"}
                 422 {"errors":[{code,category,subject_id}]}
                 400 {"error":"bad_request"|"honeypot"} (honeypot — silent)
                 429 {"error":"rate_limited"}
       ============================================================ */
    function postVote(payload) {
        return fetch('/api/v1/vote', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': BG.csrfToken || '',
                'X-Voter-Token': token()
            },
            body: JSON.stringify(payload)
        }).then(async function (res) {
            var body = await res.json().catch(function () { return {}; });
            if (res.status === 200) return body; /* {status, voters_total} */
            var err = Object.assign({ status: res.status }, body);
            if (res.status === 400 && body.error === 'honeypot') err.silent = true;
            throw err; /* контракт как у mockPostVote прототипа */
        });
    }

    /* ============================================================
       Роутер вьюх
       ============================================================ */

    var BADGE_TEXT = {
        NOT_STARTED: 'Не начато',
        ACTIVE: 'Активно',
        PAUSED: 'Пауза',
        FINISHED: 'Завершено'
    };

    function updateBadge(st) {
        if (!stateBadge) return;
        stateBadge.textContent = BADGE_TEXT[st] || st;
        stateBadge.className = 'state-badge st-' + st.toLowerCase();
    }

    function updateProgress(current) {
        if (!progressNav) return;
        progressNav.hidden = false;
        var pumpkins = progressNav.querySelectorAll('.pumpkin');
        pumpkins.forEach(function (p, i) {
            p.classList.toggle('done', i < current - 1);
            p.classList.toggle('current', i === current - 1);
            p.classList.toggle('todo', i > current - 1);
        });
        progressNav.setAttribute(
            'aria-label',
            current > 5 ? 'Прогресс: подтверждение' : 'Прогресс: шаг ' + current + ' из 5'
        );
    }

    /* route() — единая точка входа */
    function route(dir) {
        window.clearTimeout(autoTimer);
        var st = S.getState();
        updateBadge(st);

        if (S.isVoted()) return showStateView('voted', dir);          /* FR-V-10 */
        if (st === 'NOT_STARTED') return showStateView('not-started', dir); /* FR-V-11 */
        if (st === 'PAUSED') return showStateView('paused', dir);
        if (st === 'FINISHED') return showStateView('finished', dir);

        /* ACTIVE: вход сразу в голосование, 0 промежуточных экранов (FR-V-01) */
        loadDraft();
        if (draft.step === 'confirm') renderConfirm(dir);
        else {
            draft.step = Math.min(Math.max(draft.step, 1), 5);
            renderStep(draft.step, dir);
        }
    }

    /* ============================================================
       Экраны состояний (микротексты 03-Айдентика §9)
       ============================================================ */

    function showStateView(kind, dir) {
        if (progressNav) progressNav.hidden = true;
        FX.transition(viewRoot, dir, function () {
            var html = '';
            if (kind === 'not-started') {
                html =
                    '<section class="view state-view">' +
                    '<div class="state-art" aria-hidden="true">🚪</div>' +
                    '<h1 class="hero" tabindex="-1">Двери склепа ещё закрыты 🚪</h1>' +
                    '<p class="lead">Голосование откроется прямо на вечеринке. Держите телефон наготове — и костюм в порядке!</p>' +
                    '</section>';
            } else if (kind === 'paused') {
                loadDraft();
                html =
                    '<section class="view state-view">' +
                    '<div class="state-art" aria-hidden="true">☕</div>' +
                    '<h1 class="hero" tabindex="-1">Голосование на паузе — ведьмы вышли за кофе ☕🦇</h1>' +
                    '<p class="lead">Скоро вернёмся.</p>' +
                    (hasAnyChoice()
                        ? '<p class="muted">Ваш черновик сохранён — вернёмся к нему, когда допьют кофе 🕯️</p>'
                        : '') +
                    '</section>';
            } else if (kind === 'finished') {
                html =
                    '<section class="view state-view">' +
                    '<div class="state-art" aria-hidden="true">🔮</div>' +
                    '<h1 class="hero" tabindex="-1">Котёл запечатан 🔮</h1>' +
                    '<p class="lead">Голосование окончено, результаты подсчитываются.</p>' +
                    (BG.publish_results
                        ? '<a class="btn btn-primary" href="/results">Посмотреть результаты</a>'
                        : '') +
                    '</section>';
            } else { /* voted */
                html =
                    '<section class="view state-view">' +
                    '<div class="state-art" aria-hidden="true">🎃</div>' +
                    '<h1 class="hero" tabindex="-1">Вы уже отдали свой голос 🎃</h1>' +
                    '<p class="lead">Один гость — одно голосование. Спасибо! Результаты объявим на сцене.</p>' +
                    '</section>';
            }
            viewRoot.innerHTML = html;
            focusHero();
        });
    }

    /* ============================================================
       Шаги 1–5
       ============================================================ */

    var GHOST_SVG =
        '<svg viewBox="0 0 120 120" aria-hidden="true" focusable="false">' +
        '<path d="M60 16c-21 0-33 17-33 38v46l9-7 8 7 8-7 8 7 8-7 8 7 9-7V54c0-21-12-38-33-38Z" fill="currentColor"/>' +
        '<circle cx="47" cy="54" r="6" fill="#0C0716"/>' +
        '<circle cx="73" cy="54" r="6" fill="#0C0716"/>' +
        '<path d="M50 72c6 7 14 7 20 0" stroke="#0C0716" stroke-width="5" fill="none" stroke-linecap="round"/>' +
        '</svg>';

    function photoHTML(sub) {
        /* фото кандидата из БД (/photo/p/<id>.jpg, /photo/g/<id>.jpg);
           если фото нет — призрак-плейсхолдер как в прототипе */
        var url = sub.photo
            ? (sub.type === 'group' ? '/photo/g/' : '/photo/p/') + sub.id + '.jpg'
            : null;
        if (url) {
            return '<img class="card-img" src="' + url + '" alt="" loading="lazy">';
        }
        return GHOST_SVG;
    }

    function cardHTML(cat, sub) {
        var conflict = canVoteFor(cat.id, sub.type, sub.id);
        var cur = draft.choices[cat.id];
        var sel = !!(cur && cur.type === sub.type && String(cur.id) === String(sub.id));
        return (
            '<button type="button" class="card' + (sel ? ' selected' : '') + (conflict ? ' locked' : '') + '"' +
            ' data-type="' + sub.type + '" data-id="' + sub.id + '"' +
            ' aria-pressed="' + sel + '"' +
            (conflict ? ' disabled' : '') +
            (conflict ? ' title="Уже выбран в номинации «' + esc(conflict.name) + '» — один костюм не может быть везде"' : '') +
            '>' +
            '<span class="card-photo">' + photoHTML(sub) +
            '<span class="card-num" aria-hidden="true">№' + sub.number + '</span>' +
            '<span class="visually-hidden">Номер ' + sub.number + '</span>' +
            '</span>' +
            '<span class="card-name">' + esc(sub.name) + '</span>' +
            (sub.desc ? '<span class="card-desc">' + esc(sub.desc) + '</span>' : '') +
            (sub.type === 'group'
                ? '<span class="card-tag tag-group">Группа</span>'
                : '') +
            (sel
                ? '<span class="card-check" aria-hidden="true">✓</span>' +
                '<span class="card-check-sr visually-hidden">— выбрано</span>'
                : '') +
            (conflict
                ? '<span class="card-lock" aria-hidden="true">🔒 Уже выбран: ' + esc(conflict.name) + '</span>' +
                '<span class="card-lock-sr visually-hidden">Уже выбран в номинации «' + esc(conflict.name) +
                '» — один костюм не может быть везде</span>'
                : '') +
            '</button>'
        );
    }

    function gridHTML(cat, subs) {
        return '<div class="card-grid">' + subs.map(function (s) { return cardHTML(cat, s); }).join('') + '</div>';
    }

    function stepNavHTML(n) {
        return (
            '<div class="step-nav">' +
            (n > 1 ? '<button type="button" class="btn btn-secondary" id="btn-back">← Назад</button>' : '<span class="step-nav-spacer" aria-hidden="true"></span>') +
            '<button type="button" class="btn btn-ghost" id="btn-skip">Пропустить</button>' +
            '<button type="button" class="btn btn-primary" id="btn-next">Далее →</button>' +
            '</div>'
        );
    }

    function bindStepNav(n, cat) {
        var back = document.getElementById('btn-back');
        var skip = document.getElementById('btn-skip');
        var next = document.getElementById('btn-next');
        if (back) back.addEventListener('click', function () { goStep(n - 1, 'back'); });
        if (skip) {
            skip.addEventListener('click', function () {
                draft.choices[cat.id] = null; /* «Не определился» — не мешает отправке */
                saveDraft();
                goStep(n + 1, 'fwd');
            });
        }
        if (next) next.addEventListener('click', function () { goStep(n + 1, 'fwd'); });

        viewRoot.querySelectorAll('.card').forEach(function (card) {
            card.addEventListener('click', onCardClick);
        });
    }

    function onCardClick(e) {
        var card = e.currentTarget;
        if (card.disabled) return;
        var section = card.closest('.step-view');
        var catId = section ? section.dataset.cat : null;
        if (!catId) return;
        var type = card.dataset.type;
        var id = card.dataset.id;
        var cur = draft.choices[catId];

        if (cur && cur.type === type && String(cur.id) === String(id)) {
            draft.choices[catId] = null; /* повторный тап — снять выбор */
        } else {
            draft.choices[catId] = { type: type, id: id }; /* FR-V-04: тап = выбор */
        }
        saveDraft();
        refreshSelections(catId);
        FX.pop(card);
    }

    /* Обновление выбора/замков на текущем шаге без полной перерисовки */
    function refreshSelections(catId) {
        viewRoot.querySelectorAll('.card').forEach(function (card) {
            var type = card.dataset.type;
            var id = card.dataset.id;
            var conflict = canVoteFor(catId, type, id);
            var cur = draft.choices[catId];
            var sel = !!(cur && cur.type === type && String(cur.id) === String(id));

            card.classList.toggle('selected', sel);
            card.classList.toggle('locked', !!conflict);
            card.disabled = !!conflict;
            card.setAttribute('aria-pressed', String(sel));

            var check = card.querySelector('.card-check');
            var checkSr = card.querySelector('.card-check-sr');
            if (sel && !check) {
                card.insertAdjacentHTML('beforeend',
                    '<span class="card-check" aria-hidden="true">✓</span>' +
                    '<span class="card-check-sr visually-hidden">— выбрано</span>');
            } else if (!sel && check) {
                check.parentNode.removeChild(check);
                if (checkSr) checkSr.parentNode.removeChild(checkSr);
            }

            var lock = card.querySelector('.card-lock');
            var lockSr = card.querySelector('.card-lock-sr');
            if (conflict && !lock) {
                card.insertAdjacentHTML('beforeend',
                    '<span class="card-lock" aria-hidden="true">🔒 Уже выбран: ' + esc(conflict.name) + '</span>' +
                    '<span class="card-lock-sr visually-hidden">Уже выбран в номинации «' + esc(conflict.name) +
                    '» — один костюм не может быть везде</span>');
                card.title = 'Уже выбран в номинации «' + conflict.name + '» — один костюм не может быть везде';
            } else if (!conflict && lock) {
                lock.parentNode.removeChild(lock);
                if (lockSr) lockSr.parentNode.removeChild(lockSr);
                card.removeAttribute('title');
            }
        });
    }

    function renderStep(n, dir) {
        var cat = ALL_CATS[n - 1];
        var subs = subjectsFor(cat);
        draft.step = n;
        saveDraft();

        FX.transition(viewRoot, dir, function () {
            updateProgress(n);
            var hint = (n === 1)
                ? '<p class="lead">Выбирайте сердцем… если оно ещё бьётся 💀 Номинация 1 из 4</p>'
                : '';

            if (!subs.length) {
                /* Пустая номинация (E1, 03-Айдентика §9) */
                viewRoot.innerHTML =
                    '<section class="view step-view" data-cat="' + cat.id + '">' +
                    '<p class="step-count">Шаг <b>' + n + '/5</b></p>' +
                    '<h1 class="hero" tabindex="-1">' + esc(cat.name) + '</h1>' +
                    hint +
                    '<div class="empty-note">' +
                    '<div class="empty-emoji" aria-hidden="true">🕸️</div>' +
                    '<p>В этой номинации пока пусто и жутко… 🕸️</p>' +
                    '</div>' +
                    stepNavHTML(n) +
                    '</section>';
                bindStepNav(n, cat);
                focusHero();
                scheduleAutoAdvance(n);
                return;
            }

            viewRoot.innerHTML =
                '<section class="view step-view" data-cat="' + cat.id + '">' +
                '<p class="step-count">Шаг <b>' + n + '/5</b></p>' +
                '<h1 class="hero" tabindex="-1">' + esc(cat.name) + '</h1>' +
                hint +
                gridHTML(cat, subs) +
                stepNavHTML(n) +
                '</section>';
            bindStepNav(n, cat);
            focusHero();
        });
    }

    /* Автопереход с пустой номинации (E1) */
    function scheduleAutoAdvance(n) {
        window.clearTimeout(autoTimer);
        autoTimer = window.setTimeout(function () {
            if (S.getState() === 'ACTIVE' && !S.isVoted() && draft.step === n) {
                goStep(n + 1, 'fwd');
            }
        }, 1800);
    }

    function goStep(n, dir) {
        window.clearTimeout(autoTimer);
        if (n > 5) {
            draft.step = 'confirm';
            saveDraft();
            renderConfirm(dir);
            return;
        }
        if (n < 1) n = 1;
        renderStep(n, dir);
    }

    /* ============================================================
       Подтверждение (FR-V-08) — «Проверь себя 🕯️»
       ============================================================ */

    function renderConfirm(dir) {
        FX.transition(viewRoot, dir, function () {
            updateProgress(6);
            var rows = ALL_CATS.map(function (c) {
                var ch = draft.choices[c.id];
                var val;
                if (ch) {
                    var s = D.findSubject(ch.type, ch.id);
                    val =
                        '<span class="sum-thumb" aria-hidden="true">' + photoHTML(s) + '</span>' +
                        '<span>№' + s.number + ' ' + esc(s.name) + '</span>';
                } else {
                    val = '<span class="muted">пропущено</span>';
                }
                return (
                    '<li class="sum-row">' +
                    '<span class="sum-cat" style="--cat: var(' + c.colorVar + ')">' + esc(c.short) + '</span>' +
                    '<span class="sum-val">' + val + '</span>' +
                    '</li>'
                );
            }).join('');

            viewRoot.innerHTML =
                '<section class="view confirm-view">' +
                '<h1 class="hero" tabindex="-1">Проверь себя 🕯️</h1>' +
                '<p class="lead">Проверьте свой выбор. После подтверждения котёл закроется — изменить голос будет нельзя.</p>' +
                '<ul class="sum-list">' + rows + '</ul>' +
                '<p class="err" id="confirm-err" role="alert" hidden></p>' +
                '<form id="confirm-form" novalidate>' +
                '<div class="honeypot" aria-hidden="true">' +
                '<label for="website">Сайт (не заполняйте это поле)</label>' +
                '<input type="text" id="website" name="website" tabindex="-1" autocomplete="off" spellcheck="false">' +
                '</div>' +
                '<div class="confirm-nav">' +
                '<button type="button" class="btn btn-secondary" id="btn-back-confirm">← Назад</button>' +
                '<button type="submit" class="btn btn-primary btn-confirm" id="btn-confirm">Подтвердить голос 🎃</button>' +
                '</div>' +
                '</form>' +
                '</section>';

            focusHero();

            document.getElementById('btn-back-confirm').addEventListener('click', function () {
                goStep(5, 'back');
            });

            document.getElementById('confirm-form').addEventListener('submit', function (e) {
                e.preventDefault();
                submitVote();
            });
        });
    }

    function submitVote() {
        if (confirmBusy) return;
        var errBox = document.getElementById('confirm-err');
        var btn = document.getElementById('btn-confirm');
        confirmBusy = true;
        if (errBox) errBox.hidden = true;
        if (btn) { btn.disabled = true; btn.textContent = 'Котёл бурлит…'; }

        var payload = buildPayload();
        /* honeypot берём из реального поля (бот мог его заполнить) */
        var hp = document.getElementById('website');
        if (hp) payload.website = hp.value;

        postVote(payload).then(function (res) {
            /* FR-V-09: флаг «проголосовал» — теперь серверный (voted_at),
               локально — только для мгновенной перерисовки */
            S.setVoted(true);
            S.setVotersTotal(res.voters_total);
            S.clearDraft(); /* черновик — не голос */
            confirmBusy = false;
            renderSuccess(res.voters_total);
        }).catch(function (err) {
            confirmBusy = false;
            if (btn) { btn.disabled = false; btn.textContent = 'Подтвердить голос 🎃'; }
            if (err && err.silent) return; /* honeypot: молча, без подсказок боту */
            if (err && err.status === 429 && errBox) {
                errBox.textContent = 'Слишком часто — подождите минуту 🦇';
                errBox.hidden = false;
                return;
            }
            if (err && err.status === 409) { route(); return; } /* состояние/токен изменились */
            if (err && err.status === 422 && errBox) {
                var names = (err.errors || []).map(function (x) {
                    var c = ALL_CATS.filter(function (c2) { return c2.id === x.category; })[0];
                    return c ? '«' + c.name + '»' : '';
                }).filter(Boolean).join(', ');
                errBox.textContent = 'Один костюм не может быть везде: конфликт ' + names +
                    '. Вернитесь назад и измените выбор 🕷️';
                errBox.hidden = false;
                return;
            }
            if (errBox) {
                errBox.textContent = 'Котёл подавился… попробуйте ещё раз 🫠';
                errBox.hidden = false;
            }
        });
    }

    /* ============================================================
       Успех (FR-V-09) — «Голос улетел в котёл! 👻🎃»
       ============================================================ */

    function renderSuccess(total) {
        if (progressNav) progressNav.hidden = true;
        updateBadge('ACTIVE');
        FX.transition(viewRoot, 'fwd', function () {
            viewRoot.innerHTML =
                '<section class="view success-view">' +
                '<div class="state-art" aria-hidden="true">👻</div>' +
                '<h1 class="hero" tabindex="-1">Голос улетел в котёл! 👻🎃</h1>' +
                '<p class="lead">Голоса учтены. Спасибо, что выбрали лучших из лучших!</p>' +
                '<p class="muted">Изменить голос нельзя — котёл запечатан 🔮</p>' +
                '<p class="voters-counter" aria-live="polite">Вас уже <strong>' + total + '</strong> проголосовавших</p>' +
                '</section>';
            focusHero();
            FX.celebrate();
        });
    }

    /* ---------- запуск ---------- */
    route();

    /* Экспорт для отладки и будущих тестов */
    window.TG_VOTE = {
        route: route,
        canVoteFor: canVoteFor,
        buildPayload: buildPayload,
        postVote: postVote
    };
})();
