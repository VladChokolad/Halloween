/* ============================================================
   fx.js — анимации «Неонового склепа» (03-Айдентика §8).
   Всё уважает prefers-reduced-motion: reduce → мгновенные смены
   состояний. Без звука. Анимации не блокируют ввод.
   ============================================================ */
window.TG_FX = (function () {
    'use strict';

    var mqReduced = window.matchMedia('(prefers-reduced-motion: reduce)');

    function reduced() { return mqReduced.matches; }

    /* Неоновый flicker заголовка: 2 мигания за 600 мс (03 §8) */
    function flicker(el) {
        if (!el || reduced()) return;
        el.classList.remove('flicker');
        void el.offsetWidth; /* reflow — перезапуск анимации */
        el.classList.add('flicker');
        window.setTimeout(function () { el.classList.remove('flicker'); }, 700);
    }

    /* Пружинка выбора карточки: 200 мс */
    function pop(card) {
        if (!card || reduced()) return;
        card.classList.remove('pop');
        void card.offsetWidth;
        card.classList.add('pop');
    }

    /* Переход шага: слайд влево/вправо + фейд, 250 мс (03 §8).
       dir: 'fwd' — вперёд, 'back' — назад. renderFn меняет содержимое. */
    function transition(root, dir, renderFn) {
        if (reduced() || !root) { renderFn(); flicker(root && root.querySelector('.hero')); return; }

        /* первый рендер — без фазы выхода */
        var first = !root.firstChild;
        if (!first) {
            root.classList.add(dir === 'back' ? 'slide-out-right' : 'slide-out-left');
        }

        window.setTimeout(function () {
            root.classList.remove('slide-out-left', 'slide-out-right');
            renderFn();
            root.classList.add(dir === 'back' ? 'slide-in-right' : 'slide-in-left');
            flicker(root.querySelector('.hero'));
            window.setTimeout(function () {
                root.classList.remove('slide-in-left', 'slide-in-right');
            }, 280);
        }, first ? 0 : 220);
    }

    /* Успех: 6–10 летучих мышей + призрак из котла + конфетти 🎃🍬,
       суммарно ≤2.5 с, однократно (03 §8) */
    function celebrate() {
        if (reduced()) return;
        if (document.getElementById('fx-layer')) return; /* однократно */

        var layer = document.createElement('div');
        layer.id = 'fx-layer';
        layer.setAttribute('aria-hidden', 'true');

        /* летучие мыши */
        var bats = 6 + Math.floor(Math.random() * 5); /* 6–10 */
        for (var i = 0; i < bats; i++) {
            var b = document.createElement('span');
            b.className = 'fx-bat';
            b.textContent = '🦇';
            b.style.setProperty('--y', (8 + Math.random() * 55) + 'vh');
            b.style.setProperty('--d', (0.9 + Math.random() * 1.1) + 's');
            b.style.setProperty('--delay', (Math.random() * 0.5) + 's');
            b.style.setProperty('--s', (0.8 + Math.random() * 0.9).toFixed(2));
            layer.appendChild(b);
        }

        /* призрак всплывает из котла */
        var ghost = document.createElement('span');
        ghost.className = 'fx-ghost';
        ghost.textContent = '👻';
        layer.appendChild(ghost);

        /* конфетти */
        var conf = ['🎃', '🍬', '🍫', '👻'];
        for (var j = 0; j < 26; j++) {
            var c = document.createElement('span');
            c.className = 'fx-confetti';
            c.textContent = conf[j % conf.length];
            c.style.setProperty('--x', (2 + Math.random() * 96) + 'vw');
            c.style.setProperty('--d', (1.3 + Math.random() * 1.0) + 's');
            c.style.setProperty('--delay', (Math.random() * 0.4) + 's');
            c.style.setProperty('--s', (0.7 + Math.random() * 0.8).toFixed(2));
            layer.appendChild(c);
        }

        document.body.appendChild(layer);
        window.setTimeout(function () {
            if (layer.parentNode) layer.parentNode.removeChild(layer);
        }, 2600); /* ≤2.5 с + запас на cleanup */
    }

    return {
        reduced: reduced,
        flicker: flicker,
        pop: pop,
        transition: transition,
        celebrate: celebrate
    };
})();
