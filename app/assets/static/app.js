async function warmHealthCheck() {
    try {
        await fetch('/health');
    } catch (_error) {
        // Web scaffold only; no user-facing error yet.
    }
}

const jadeLoadingAssetUrls = [
    '/static/images/themes/jade/theme-loading-jade-panel-v2.png?v=20260706-jade-loading-assets-v1',
    '/static/images/themes/jade/theme-loading-jade-sword-primary-v2.png?v=20260706-jade-loading-assets-v1',
    '/static/images/themes/jade/theme-loading-jade-sword-rival-v2.png?v=20260706-jade-loading-assets-v1',
];
let jadeLoadingAssetsPromise = null;
let jadeLoadingAssetsReady = false;
const globalLoadingMinimumFrameMs = 220;
const profileRefreshLoadingHoldMs = 160;
const profileSwitchRefreshStorageKey = 'profile-switch-refresh-needed';
const queuedSecondTickers = Array.isArray(window.appSecondTickers)
    ? window.appSecondTickers.slice()
    : [];
const secondTickerCallbacks = new Set();
let secondTickerIntervalId = null;

function decodeImageElement(image) {
    return new Promise((resolve) => {
        let settled = false;
        const finish = async (loaded) => {
            if (settled) return;
            settled = true;
            image.removeEventListener('load', handleLoad);
            image.removeEventListener('error', handleError);
            if (loaded && typeof image.decode === 'function') {
                try {
                    await image.decode();
                } catch (_error) {
                    // Loaded images can still throw on decode in older browsers; use the loaded bitmap.
                }
            }
            resolve(loaded && image.naturalWidth > 0);
        };
        const handleLoad = () => finish(true);
        const handleError = () => finish(false);
        if (image.complete) {
            finish(image.naturalWidth > 0);
            return;
        }
        image.addEventListener('load', handleLoad, { once: true });
        image.addEventListener('error', handleError, { once: true });
    });
}

function decodeImageAsset(src) {
    const image = new Image();
    image.decoding = 'async';
    image.src = src;
    return decodeImageElement(image);
}

function getJadeLoadingAssetImages() {
    return Array.from(document.querySelectorAll('[data-jade-loading-asset]'))
        .filter((image) => image instanceof HTMLImageElement);
}

function warmDomJadeLoadingAssets() {
    const images = getJadeLoadingAssetImages();
    if (!images.length) {
        return Promise.all(jadeLoadingAssetUrls.map(decodeImageAsset));
    }
    return Promise.all(images.map(decodeImageElement));
}

function warmJadeLoadingAssets() {
    if (jadeLoadingAssetsReady) {
        document.documentElement.dataset.jadeLoadingAssets = 'ready';
        return jadeLoadingAssetsPromise || Promise.resolve(true);
    }
    if (!jadeLoadingAssetsPromise) {
        document.documentElement.dataset.jadeLoadingAssets = 'pending';
        jadeLoadingAssetsPromise = warmDomJadeLoadingAssets().then((results) => {
            jadeLoadingAssetsReady = results.every(Boolean);
            document.documentElement.dataset.jadeLoadingAssets = jadeLoadingAssetsReady ? 'ready' : 'error';
            if (!jadeLoadingAssetsReady) {
                jadeLoadingAssetsPromise = null;
            }
            return jadeLoadingAssetsReady;
        });
    }
    return jadeLoadingAssetsPromise;
}

function prepareGlobalLoading() {
    if (document.documentElement.dataset.theme === 'jade') {
        return warmJadeLoadingAssets();
    }
    return Promise.resolve(true);
}

function waitForNextPaint() {
    return new Promise((resolve) => {
        window.requestAnimationFrame(() => {
            window.requestAnimationFrame(resolve);
        });
    });
}

function waitForLoadingMinimumFrame() {
    return new Promise((resolve) => {
        window.setTimeout(resolve, globalLoadingMinimumFrameMs);
    });
}

function isProfileSwitchForm(form) {
    try {
        const targetUrl = new URL(form.action, window.location.href);
        return targetUrl.origin === window.location.origin &&
            /^\/profiles\/\d+\/switch$/.test(targetUrl.pathname);
    } catch (_error) {
        return false;
    }
}

function markProfileSwitchRefreshNeeded(form) {
    if (!isProfileSwitchForm(form)) return;
    try {
        window.sessionStorage.setItem(profileSwitchRefreshStorageKey, '1');
    } catch (_error) {
        // Profile switching still works when sessionStorage is unavailable.
    }
}

function consumeProfileSwitchRefreshNeeded() {
    try {
        const value = window.sessionStorage.getItem(profileSwitchRefreshStorageKey);
        if (value !== '1') return false;
        window.sessionStorage.removeItem(profileSwitchRefreshStorageKey);
        return true;
    } catch (_error) {
        return false;
    }
}

function primeProfileRefreshLoading(
    overlay = document.getElementById('global-loading-overlay'),
    message = document.getElementById('global-loading-message'),
) {
    if (window.location.pathname !== '/profile') return false;
    try {
        if (window.sessionStorage.getItem(profileSwitchRefreshStorageKey) !== '1') {
            return false;
        }
    } catch (_error) {
        return false;
    }
    if (message) {
        message.textContent = '正在刷新当前元神';
    }
    if (overlay) {
        overlay.hidden = false;
    }
    document.documentElement.dataset.profileRefreshLoading = '1';
    document.body.classList.add('is-global-loading');
    document.documentElement.setAttribute('aria-busy', 'true');
    return true;
}

async function showGlobalLoading(overlay, message, messageText, options = {}) {
    if (message) {
        message.textContent = messageText || '正在处理';
    }
    const ready = await prepareGlobalLoading();
    if (
        !ready &&
        document.documentElement.dataset.theme === 'jade' &&
        !options.allowUnready
    ) {
        return false;
    }
    if (overlay) {
        overlay.hidden = false;
    }
    document.body.classList.add('is-global-loading');
    document.documentElement.setAttribute('aria-busy', 'true');
    await waitForNextPaint();
    await waitForLoadingMinimumFrame();
    return true;
}

function hideGlobalLoading(overlay = document.getElementById('global-loading-overlay')) {
    if (overlay) {
        overlay.hidden = true;
    }
    document.body.classList.remove('is-global-loading');
    document.documentElement.removeAttribute('aria-busy');
}

function unregisterSecondTicker(callback) {
    secondTickerCallbacks.delete(callback);
    if (!secondTickerCallbacks.size && secondTickerIntervalId !== null) {
        window.clearInterval(secondTickerIntervalId);
        secondTickerIntervalId = null;
    }
}

function runSecondTickers() {
    if (document.hidden) return;
    secondTickerCallbacks.forEach((callback) => callback());
}

function registerSecondTicker(callback) {
    if (typeof callback !== 'function') return;
    secondTickerCallbacks.add(callback);
    if (secondTickerIntervalId === null) {
        secondTickerIntervalId = window.setInterval(runSecondTickers, 1000);
    }
}

function waitForDocumentVisible() {
    if (!document.hidden) return Promise.resolve();
    return new Promise((resolve) => {
        const handleVisibilityChange = () => {
            if (document.hidden) return;
            document.removeEventListener('visibilitychange', handleVisibilityChange);
            resolve();
        };
        document.addEventListener('visibilitychange', handleVisibilityChange);
    });
}

window.appSecondTickers = {
    push(callback) {
        registerSecondTicker(callback);
        return secondTickerCallbacks.size;
    },
};
queuedSecondTickers.forEach(registerSecondTicker);
document.addEventListener('visibilitychange', () => {
    if (!document.hidden) runSecondTickers();
});

function formatCountdown(seconds) {
    const safe = Math.max(0, Math.floor(seconds));
    if (safe <= 0) return '已到期';
    const hours = Math.floor(safe / 3600);
    const minutes = Math.floor((safe % 3600) / 60);
    const secs = safe % 60;
    const parts = [];
    if (hours) parts.push(`${hours}小时`);
    if (minutes) parts.push(`${minutes}分钟`);
    if (secs || !parts.length) parts.push(`${secs}秒`);
    return parts.join('');
}

function mountCountdowns(root = document) {
    const items = Array.from(root.querySelectorAll('[data-countdown-target]'));
    if (!items.length) return;

    let unregister = null;
    const tick = () => {
        if (root instanceof Element && !root.isConnected) {
            if (unregister) unregister();
            return;
        }
        const now = Date.now() / 1000;
        items.forEach((item) => {
            const target = Number(item.dataset.countdownTarget || 0);
            if (!target) {
                item.textContent = '-';
                return;
            }
            item.textContent = formatCountdown(target - now);
        });
    };

    tick();
    registerSecondTicker(tick);
    unregister = () => unregisterSecondTicker(tick);
}

function mountGlobalLoadingForms() {
    let loadingActive = false;
    const overlay = document.getElementById('global-loading-overlay');
    const message = document.getElementById('global-loading-message');
    if (!overlay) return;

    const resetLoadingState = () => {
        loadingActive = false;
        delete document.documentElement.dataset.profileRefreshLoading;
        hideGlobalLoading(overlay);
    };

    window.addEventListener('pageshow', (event) => {
        if (window.location.pathname !== '/profile') {
            resetLoadingState();
            return;
        }
        if (!event.persisted) {
            consumeProfileSwitchRefreshNeeded();
            resetLoadingState();
            return;
        }
        if (!primeProfileRefreshLoading(overlay, message)) {
            resetLoadingState();
            return;
        }
        consumeProfileSwitchRefreshNeeded();
        loadingActive = true;
        showGlobalLoading(
            overlay,
            message,
            '正在刷新当前元神',
            { allowUnready: true },
        )
            .then(async () => {
                await new Promise((resolve) => {
                    window.setTimeout(resolve, profileRefreshLoadingHoldMs);
                });
                window.location.reload();
            });
    });

    document.addEventListener('submit', (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || !form.matches('[data-global-loading]')) {
            return;
        }
        if (form.matches('[data-confirm-dialog]') && form.dataset.confirmed !== '1') {
            return;
        }
        if (form.dataset.loadingReadySubmit === '1') {
            delete form.dataset.loadingReadySubmit;
            return;
        }
        if (loadingActive) {
            event.preventDefault();
            return;
        }
        event.preventDefault();
        loadingActive = true;
        showGlobalLoading(overlay, message, form.dataset.loadingMessage || '正在处理')
            .then(() => {
                markProfileSwitchRefreshNeeded(form);
                form.dataset.loadingReadySubmit = '1';
                form.requestSubmit();
            });
    });
}

function mountPartialCardRefresh(card) {
    if (!(card instanceof HTMLElement) || card.dataset.cardRefreshMounted === '1') {
        return;
    }
    const cardKey = card.dataset.partialRefreshCard || '';
    if (!cardKey) return;
    card.dataset.cardRefreshMounted = '1';
    let loading = false;

    card.addEventListener('submit', async (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || !form.matches('[data-partial-card-refresh]')) {
            return;
        }
        event.preventDefault();
        if (loading) return;

        loading = true;
        card.setAttribute('aria-busy', 'true');
        const overlay = document.getElementById('global-loading-overlay');
        const message = document.getElementById('global-loading-message');
        const activeArtifactTab = card.querySelector('[data-artifact-tab-target][aria-selected="true"]');
        const activeArtifactTabTarget = activeArtifactTab?.dataset.artifactTabTarget || '';
        await showGlobalLoading(overlay, message, form.dataset.loadingMessage || '正在刷新卡片');

        try {
            const previousTop = card.getBoundingClientRect().top;
            const response = await fetch(form.action, {
                method: (form.method || 'post').toUpperCase(),
                body: new FormData(form),
                credentials: 'same-origin',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            });
            if (!response.ok) {
                throw new Error(`Card refresh failed: ${response.status}`);
            }

            const html = await response.text();
            const doc = new DOMParser().parseFromString(html, 'text/html');
            const nextCard = doc.querySelector(`[data-partial-refresh-card="${cardKey}"]`);
            if (!(nextCard instanceof HTMLElement)) {
                throw new Error('Refresh card missing from response');
            }

            card.replaceWith(nextCard);
            if (typeof mountOtherCommandBuilders === 'function') {
                mountOtherCommandBuilders(nextCard);
            }
            if (typeof mountArtifactCardTabs === 'function') {
                mountArtifactCardTabs(nextCard, activeArtifactTabTarget);
            }
            mountCountdowns(nextCard);
            mountPartialCardRefresh(nextCard);
            const nextTop = nextCard.getBoundingClientRect().top;
            window.scrollBy(0, nextTop - previousTop);
        } catch (_error) {
            window.alert('操作失败，当前卡片未刷新，请稍后重试。');
        } finally {
            hideGlobalLoading(overlay);
            if (card.isConnected) {
                loading = false;
                card.removeAttribute('aria-busy');
            }
        }
    });
}

function mountPartialCardRefreshes(root = document) {
    const cards = [];
    if (root instanceof Element && root.matches('[data-partial-refresh-card]')) {
        cards.push(root);
    }
    root.querySelectorAll('[data-partial-refresh-card]').forEach((card) => cards.push(card));
    cards.forEach(mountPartialCardRefresh);
}

function mountNavigationTransitions() {
    const content = document.querySelector('.content');
    const overlay = document.getElementById('global-loading-overlay');
    const message = document.getElementById('global-loading-message');
    const navLinks = Array.from(document.querySelectorAll('.nav a[href]'));
    if (!content || !navLinks.length) return;

    let navigating = false;
    const isCurrentRoute = (url) => (
        url.origin === window.location.origin &&
        url.pathname === window.location.pathname &&
        url.search === window.location.search
    );
    const findCurrentNavLink = () => navLinks.find((link) => {
        const url = new URL(link.href, window.location.href);
        return url.origin === window.location.origin && url.pathname === window.location.pathname;
    }) || null;
    let currentNavLink = findCurrentNavLink() ||
        navLinks.find((link) => link.classList.contains('active')) ||
        null;

    const reset = () => {
        navigating = false;
        const preserveProfileRefreshLoading =
            document.documentElement.dataset.profileRefreshLoading === '1';
        if (!preserveProfileRefreshLoading) {
            overlay?.setAttribute('hidden', '');
            document.body.classList.remove('is-global-loading');
            document.documentElement.removeAttribute('aria-busy');
        }
        content.classList.remove('is-route-exiting', 'is-route-loading');
        document.body.classList.remove('is-route-navigating');
        currentNavLink = findCurrentNavLink() ||
            navLinks.find((link) => link.classList.contains('active')) ||
            currentNavLink;
        navLinks.forEach((link) => {
            link.classList.remove('active', 'is-route-pending');
            if (link === currentNavLink) {
                link.classList.add('active');
                link.setAttribute('aria-current', 'page');
            } else {
                link.removeAttribute('aria-current');
            }
        });
    };

    navLinks.forEach((link) => {
        link.addEventListener('click', (event) => {
            if (
                event.defaultPrevented ||
                event.button !== 0 ||
                event.metaKey ||
                event.ctrlKey ||
                event.shiftKey ||
                event.altKey
            ) {
                return;
            }
            if (link.target && link.target !== '_self') {
                return;
            }

            const targetUrl = new URL(link.href, window.location.href);
            if (targetUrl.origin !== window.location.origin) {
                return;
            }
            if (link === currentNavLink || isCurrentRoute(targetUrl)) {
                event.preventDefault();
                return;
            }

            event.preventDefault();
            navigating = true;
            navLinks.forEach((navLink) => {
                navLink.classList.remove('active', 'is-route-pending');
                navLink.removeAttribute('aria-current');
            });
            link.classList.add('active', 'is-route-pending');
            link.setAttribute('aria-current', 'page');
            currentNavLink = link;
            content.classList.add('is-route-exiting', 'is-route-loading');
            document.body.classList.add('is-route-navigating', 'is-global-loading');
            document.documentElement.setAttribute('aria-busy', 'true');
            if (message) {
                message.textContent = '正在切换';
            }
            if (overlay) {
                overlay.hidden = false;
            }
            waitForNextPaint().then(() => {
                window.location.href = targetUrl.href;
            });
        });
    });

    window.addEventListener('pageshow', reset);
}

function mountTianxingRewardDateLookup() {
    const findRewardSection = (root) => {
        const explicitSection = root.querySelector('[data-tianxing-reward-section]');
        if (explicitSection) return explicitSection;
        const rewardForm = root.querySelector('[data-tianxing-reward-date-form]');
        return rewardForm?.closest('[data-tianxing-reward-section], .detail-grid, .detail-card') || null;
    };

    const section = findRewardSection(document);
    if (!section || section.dataset.tianxingRewardMounted === '1') return;

    const form = section.querySelector('[data-tianxing-reward-date-form]');
    if (!(form instanceof HTMLFormElement)) return;

    const todayLink = section.querySelector('[data-tianxing-reward-today]');
    const dateInput = form.querySelector('[data-tianxing-reward-date-input]');
    const calendarToggle = form.querySelector('[data-tianxing-reward-calendar-toggle]');
    const calendar = form.querySelector('[data-tianxing-reward-calendar]');
    const markedDaysSource = section.querySelector('[data-tianxing-reward-marked-days]');
    const submitButton = form.querySelector('button[type="submit"]');
    const originalSubmitText = submitButton instanceof HTMLButtonElement ? submitButton.textContent : '';
    let loading = false;
    section.dataset.tianxingRewardMounted = '1';

    const pad2 = (value) => String(value).padStart(2, '0');
    const dateKeyFromParts = (year, month, day) => `${year}-${pad2(month)}-${pad2(day)}`;
    const normalizeDateKey = (value) => {
        const raw = String(value || '').trim().replace(/\//g, '-');
        const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if (!match) return null;
        const year = Number(match[1]);
        const month = Number(match[2]);
        const day = Number(match[3]);
        const date = new Date(year, month - 1, day);
        if (
            date.getFullYear() !== year ||
            date.getMonth() !== month - 1 ||
            date.getDate() !== day
        ) {
            return null;
        }
        return { key: dateKeyFromParts(year, month, day), year, month, day };
    };
    const todayParts = (() => {
        const today = new Date();
        return {
            key: dateKeyFromParts(today.getFullYear(), today.getMonth() + 1, today.getDate()),
            year: today.getFullYear(),
            month: today.getMonth() + 1,
            day: today.getDate(),
        };
    })();
    const markedDays = (() => {
        try {
            const values = JSON.parse(markedDaysSource?.textContent || '[]');
            if (!Array.isArray(values)) return new Set();
            return new Set(values.map((value) => normalizeDateKey(value)?.key).filter(Boolean));
        } catch (_error) {
            return new Set();
        }
    })();
    const initialCalendarParts = normalizeDateKey(dateInput?.value) || todayParts;
    let visibleCalendarYear = initialCalendarParts.year;
    let visibleCalendarMonth = initialCalendarParts.month;

    const closeCalendar = () => {
        if (!(calendar instanceof HTMLElement)) return;
        calendar.hidden = true;
        if (calendarToggle instanceof HTMLButtonElement) {
            calendarToggle.setAttribute('aria-expanded', 'false');
        }
    };

    const renderCalendar = () => {
        if (!(calendar instanceof HTMLElement)) return;
        const selectedParts = normalizeDateKey(dateInput?.value);
        const firstDay = new Date(visibleCalendarYear, visibleCalendarMonth - 1, 1);
        const startOffset = (firstDay.getDay() + 6) % 7;
        const daysInMonth = new Date(visibleCalendarYear, visibleCalendarMonth, 0).getDate();
        const prevMonthDays = new Date(visibleCalendarYear, visibleCalendarMonth - 1, 0).getDate();
        calendar.innerHTML = '';

        const header = document.createElement('div');
        header.className = 'tianxing-calendar-header';
        const prevButton = document.createElement('button');
        prevButton.type = 'button';
        prevButton.className = 'inline-button tianxing-calendar-nav';
        prevButton.textContent = '<';
        prevButton.setAttribute('aria-label', '上一月');
        prevButton.addEventListener('click', () => {
            visibleCalendarMonth -= 1;
            if (visibleCalendarMonth < 1) {
                visibleCalendarMonth = 12;
                visibleCalendarYear -= 1;
            }
            renderCalendar();
        });
        const title = document.createElement('strong');
        title.className = 'tianxing-calendar-title';
        title.textContent = `${visibleCalendarYear}年${pad2(visibleCalendarMonth)}月`;
        const nextButton = document.createElement('button');
        nextButton.type = 'button';
        nextButton.className = 'inline-button tianxing-calendar-nav';
        nextButton.textContent = '>';
        nextButton.setAttribute('aria-label', '下一月');
        nextButton.addEventListener('click', () => {
            visibleCalendarMonth += 1;
            if (visibleCalendarMonth > 12) {
                visibleCalendarMonth = 1;
                visibleCalendarYear += 1;
            }
            renderCalendar();
        });
        header.append(prevButton, title, nextButton);
        calendar.append(header);

        const grid = document.createElement('div');
        grid.className = 'tianxing-calendar-grid';
        ['一', '二', '三', '四', '五', '六', '日'].forEach((weekday) => {
            const label = document.createElement('span');
            label.className = 'tianxing-calendar-weekday';
            label.textContent = weekday;
            grid.append(label);
        });
        for (let index = 0; index < 42; index += 1) {
            const cellDay = index - startOffset + 1;
            let year = visibleCalendarYear;
            let month = visibleCalendarMonth;
            let day = cellDay;
            let isOutside = false;
            if (cellDay < 1) {
                month -= 1;
                if (month < 1) {
                    month = 12;
                    year -= 1;
                }
                day = prevMonthDays + cellDay;
                isOutside = true;
            } else if (cellDay > daysInMonth) {
                month += 1;
                if (month > 12) {
                    month = 1;
                    year += 1;
                }
                day = cellDay - daysInMonth;
                isOutside = true;
            }
            const key = dateKeyFromParts(year, month, day);
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'tianxing-calendar-day';
            button.dataset.calendarDate = key;
            button.textContent = String(day);
            if (isOutside) button.classList.add('is-outside');
            if (markedDays.has(key)) {
                button.classList.add('has-data');
                button.setAttribute('aria-label', `${key} 有探索收益记录`);
            }
            if (selectedParts?.key === key) button.classList.add('is-selected');
            grid.append(button);
        }
        calendar.append(grid);
    };

    const openCalendar = () => {
        if (!(calendar instanceof HTMLElement)) return;
        const currentParts = normalizeDateKey(dateInput?.value);
        if (currentParts) {
            visibleCalendarYear = currentParts.year;
            visibleCalendarMonth = currentParts.month;
        }
        renderCalendar();
        calendar.hidden = false;
        if (calendarToggle instanceof HTMLButtonElement) {
            calendarToggle.setAttribute('aria-expanded', 'true');
        }
    };

    if (
        dateInput instanceof HTMLInputElement &&
        calendar instanceof HTMLElement &&
        calendarToggle instanceof HTMLButtonElement
    ) {
        renderCalendar();
        dateInput.addEventListener('focus', openCalendar);
        dateInput.addEventListener('click', openCalendar);
        dateInput.addEventListener('input', () => {
            const currentParts = normalizeDateKey(dateInput.value);
            if (currentParts) {
                visibleCalendarYear = currentParts.year;
                visibleCalendarMonth = currentParts.month;
                renderCalendar();
            }
        });
        calendarToggle.addEventListener('click', () => {
            if (calendar.hidden) {
                openCalendar();
            } else {
                closeCalendar();
            }
        });
        calendar.addEventListener('click', (event) => {
            const target = event.target instanceof Element ? event.target : null;
            const dayButton = target?.closest('[data-calendar-date]');
            if (!(dayButton instanceof HTMLButtonElement)) return;
            const selectedKey = normalizeDateKey(dateInput.value)?.key;
            const nextKey = dayButton.dataset.calendarDate || '';
            closeCalendar();
            if (!nextKey || selectedKey === nextKey) return;
            dateInput.value = nextKey;
            const currentParts = normalizeDateKey(dateInput.value);
            if (currentParts) {
                visibleCalendarYear = currentParts.year;
                visibleCalendarMonth = currentParts.month;
            }
            renderCalendar();
            form.requestSubmit();
        });
        const handleDocumentClick = (event) => {
            if (!section.isConnected) {
                document.removeEventListener('click', handleDocumentClick);
                return;
            }
            if (calendar.hidden) return;
            const eventPath = event.composedPath();
            if (
                eventPath.includes(calendar) ||
                eventPath.includes(dateInput) ||
                eventPath.includes(calendarToggle)
            ) {
                return;
            }
            closeCalendar();
        };
        document.addEventListener('click', handleDocumentClick);
        const handleDocumentKeydown = (event) => {
            if (!section.isConnected) {
                document.removeEventListener('keydown', handleDocumentKeydown);
                return;
            }
            if (event.key === 'Escape') closeCalendar();
        };
        document.addEventListener('keydown', handleDocumentKeydown);
    }

    const buildFormUrl = () => {
        const targetUrl = new URL(form.action, window.location.href);
        const params = new URLSearchParams();
        new FormData(form).forEach((value, key) => {
            if (typeof value !== 'string') return;
            const trimmedValue = value.trim();
            if (trimmedValue) {
                params.set(key, trimmedValue);
            }
        });
        targetUrl.search = params.toString();
        return targetUrl;
    };

    const setLoading = (active) => {
        section.setAttribute('aria-busy', active ? 'true' : 'false');
        if (submitButton instanceof HTMLButtonElement) {
            submitButton.disabled = active;
            submitButton.textContent = active ? '查询中' : originalSubmitText;
        }
        if (todayLink instanceof HTMLAnchorElement) {
            todayLink.setAttribute('aria-disabled', active ? 'true' : 'false');
        }
    };

    const loadRewardSection = async (targetUrl) => {
        if (loading) return;
        if (targetUrl.origin !== window.location.origin) {
            window.location.href = targetUrl.href;
            return;
        }

        loading = true;
        setLoading(true);
        const overlay = document.getElementById('global-loading-overlay');
        const message = document.getElementById('global-loading-message');
        await showGlobalLoading(overlay, message, form.dataset.loadingMessage || '正在刷新探索收益');
        try {
            const previousTop = section.getBoundingClientRect().top;
            const response = await fetch(targetUrl.href, {
                credentials: 'same-origin',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            });
            if (!response.ok) {
                throw new Error(`Reward lookup failed: ${response.status}`);
            }

            const html = await response.text();
            const doc = new DOMParser().parseFromString(html, 'text/html');
            const nextSection = findRewardSection(doc);
            if (!nextSection) {
                throw new Error('Reward section missing from response');
            }

            section.replaceWith(nextSection);
            const nextTop = nextSection.getBoundingClientRect().top;
            window.scrollBy(0, nextTop - previousTop);
            window.history.replaceState(window.history.state, '', targetUrl.href);
            mountTianxingRewardDateLookup();
        } catch (_error) {
            window.location.href = targetUrl.href;
        } finally {
            hideGlobalLoading(overlay);
            if (section.isConnected) {
                loading = false;
                setLoading(false);
            }
        }
    };

    form.addEventListener('submit', (event) => {
        event.preventDefault();
        loadRewardSection(buildFormUrl());
    });

    if (todayLink instanceof HTMLAnchorElement) {
        todayLink.addEventListener('click', (event) => {
            if (
                event.defaultPrevented ||
                event.button !== 0 ||
                event.metaKey ||
                event.ctrlKey ||
                event.shiftKey ||
                event.altKey
            ) {
                return;
            }
            event.preventDefault();
            loadRewardSection(new URL(todayLink.href, window.location.href));
        });
    }
}

function mountGlobalConfirmDialogForms() {
    const dialog = document.getElementById('global-confirm-dialog');
    const title = document.getElementById('global-confirm-title');
    const message = document.getElementById('global-confirm-message');
    const cancelButton = document.getElementById('global-confirm-cancel');
    const acceptButton = document.getElementById('global-confirm-accept');
    let pendingForm = null;
    if (!dialog || !cancelButton || !acceptButton) return;

    document.addEventListener('submit', (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || !form.matches('[data-confirm-dialog]')) {
            return;
        }
        if (form.dataset.confirmed === '1') {
            return;
        }

        event.preventDefault();
        pendingForm = form;
        if (title) title.textContent = form.dataset.confirmTitle || '确认操作';
        if (message) message.textContent = form.dataset.confirmMessage || '是否继续？';
        dialog.showModal();
    });

    cancelButton.addEventListener('click', () => {
        pendingForm = null;
        dialog.close('cancel');
    });

    acceptButton.addEventListener('click', () => {
        const form = pendingForm;
        pendingForm = null;
        if (!form) {
            dialog.close('confirm');
            return;
        }
        ['confirm_1', 'confirm_2', 'confirm_3'].forEach((name) => {
            const input = form.querySelector(`input[name="${name}"]`);
            if (input) input.value = '1';
        });
        form.dataset.confirmed = '1';
        dialog.close('confirm');
        window.setTimeout(() => form.requestSubmit(), 0);
    });
}

function mountGlobalResultDialog() {
    const dialog = document.getElementById('global-result-dialog');
    const closeButton = dialog?.querySelector('[data-global-result-close]');
    if (!(dialog instanceof HTMLDialogElement) || !(closeButton instanceof HTMLButtonElement)) {
        return;
    }
    closeButton.addEventListener('click', () => dialog.close('close'));
    if (dialog.dataset.autoOpen === '1') {
        dialog.showModal();
        const url = new URL(window.location.href);
        url.searchParams.delete('bot_sync_result');
        window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
    }
}

function mountThemeSwitcher() {
    const key = 'tianji-theme';
    const fallback = 'jade';
    const allowed = new Set(['jade', 'dark-gold', 'star', 'cinnabar']);
    const icons = new Map([
        ['dark-gold', '/static/images/themes/dark-gold/theme-logo-dark-gold.png'],
        ['jade', '/static/images/themes/jade/theme-logo-jade-sword-v1.png?v=20260705-jade-sword-logo-v1'],
        ['star', '/static/images/themes/star/theme-logo-star.png'],
        ['cinnabar', '/static/images/themes/cinnabar/theme-logo-cinnabar.png'],
    ]);
    const switcher = document.querySelector('[data-theme-switcher]');
    const trigger = document.querySelector('[data-theme-trigger]');
    const menu = document.querySelector('[data-theme-menu]');
    const currentLabel = document.querySelector('[data-theme-current]');
    const triggerPreview = document.querySelector('[data-theme-trigger-preview]');
    const themeIcon = document.querySelector('[data-theme-icon]');
    const options = Array.from(document.querySelectorAll('[data-theme-option]'));
    const optionByTheme = new Map(options.map((option) => [option.dataset.themeOption, option]));
    const labels = new Map(options.map((option) => [
        option.dataset.themeOption,
        option.dataset.themeLabel || option.textContent.trim()
    ]));

    const normalize = (value) => allowed.has(value) ? value : fallback;
    const apply = (value) => {
        const theme = normalize(value);
        document.documentElement.dataset.theme = theme;
        if (themeIcon) themeIcon.href = icons.get(theme) || icons.get(fallback);
        if (currentLabel) currentLabel.textContent = labels.get(theme) || labels.get(fallback) || theme;
        if (triggerPreview) triggerPreview.dataset.themePreview = theme;
        if (trigger) trigger.dataset.themeValue = theme;
        if (theme === 'jade') warmJadeLoadingAssets();
        options.forEach((option) => {
            const selected = option.dataset.themeOption === theme;
            option.setAttribute('aria-selected', selected ? 'true' : 'false');
            option.tabIndex = selected ? 0 : -1;
        });
        return theme;
    };

    const persist = (theme) => {
        try {
            window.localStorage.setItem(key, theme);
        } catch (_error) {
            // Theme switching remains usable without persistence.
        }
    };

    const setExpanded = (expanded, focusSelected = false) => {
        if (!trigger || !menu || !switcher) return;
        trigger.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        menu.hidden = !expanded;
        switcher.classList.toggle('open', expanded);
        if (expanded && focusSelected) {
            const selected = optionByTheme.get(document.documentElement.dataset.theme) || options[0];
            window.setTimeout(() => selected?.focus(), 0);
        }
    };

    const focusOption = (index) => {
        if (!options.length) return;
        const next = (index + options.length) % options.length;
        options[next].focus();
    };

    const chooseOption = (option) => {
        const theme = apply(option.dataset.themeOption);
        persist(theme);
        setExpanded(false);
        trigger?.focus();
    };

    let saved = fallback;
    try {
        saved = window.localStorage.getItem(key) || fallback;
    } catch (_error) {
        saved = fallback;
    }
    apply(saved);

    if (!switcher || !trigger || !menu || !options.length) return;

    trigger.addEventListener('click', (event) => {
        event.stopPropagation();
        const expanded = trigger.getAttribute('aria-expanded') === 'true';
        setExpanded(!expanded, !expanded);
    });

    trigger.addEventListener('keydown', (event) => {
        if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            setExpanded(true, true);
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            setExpanded(true);
            focusOption(options.length - 1);
        } else if (event.key === 'Escape') {
            setExpanded(false);
        }
    });

    options.forEach((option, index) => {
        option.addEventListener('click', (event) => {
            event.stopPropagation();
            chooseOption(option);
        });

        option.addEventListener('keydown', (event) => {
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                focusOption(index + 1);
            } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                focusOption(index - 1);
            } else if (event.key === 'Home') {
                event.preventDefault();
                focusOption(0);
            } else if (event.key === 'End') {
                event.preventDefault();
                focusOption(options.length - 1);
            } else if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                chooseOption(option);
            } else if (event.key === 'Escape' || event.key === 'Tab') {
                setExpanded(false);
                if (event.key === 'Escape') {
                    trigger.focus();
                }
            }
        });
    });

    document.addEventListener('click', (event) => {
        if (!switcher.contains(event.target)) {
            setExpanded(false);
        }
    });
}

function mountBrandSloganCarousel() {
    const slogan = document.querySelector('[data-brand-slogan]');
    if (!slogan) return;

    const slogans = [
        '凡人亦可修仙，步步皆是仙途',
        '一念入道，万象随心而转',
        '静候机缘，诸法自有回响',
        '洞察天机，行止皆有章法',
        '山河入局，灵机不负有心人',
        '云开见月，道心自明',
        '灵光一现，机缘已至',
        '心守本源，万法归真',
        '清风入袖，仙路无尘',
        '一卷天书，照见前程',
        '炉火微明，丹意初成',
        '剑气藏锋，只待出鞘',
        '星斗为盘，步步成局',
        '灵脉有声，道途有引',
        '一息静修，百念归一',
        '玉简轻启，玄机自现',
        '仙途漫漫，心灯长明',
        '山门未远，云路初开',
        '法诀在心，行稳致远',
        '天地为炉，道心为火',
        '灵息流转，境界渐明',
        '尘缘暂歇，仙缘正起',
        '一念清明，诸事可成',
        '观星问道，顺势而行',
        '风起青岚，剑指云霄',
        '洞府无声，灵机自生',
        '乾坤有序，修行有期',
        '灵台澄澈，万象可观',
        '不争一时，只争大道',
        '静坐观心，动则成法',
        '宝光入匣，锋芒自敛',
        '云水之间，道意长存',
        '机缘未晚，道心不迟',
        '一符落定，诸事从容',
        '灵溪照影，心境无波',
        '仙府灯明，诸法归位',
        '问道不止，步履不停',
        '破雾寻真，拨云见道',
        '玄关一启，天地皆宽',
        '星河在上，心法在身',
        '收息凝神，静候花开',
        '法宝有灵，护道长行',
        '丹香未散，境界已新',
        '踏云而上，不负此身',
        '天机轻转，福缘暗生',
        '灵田春至，万物可期',
        '一剑无声，万念皆平',
        '心有长灯，夜亦如昼',
        '山高水远，道在脚下',
        '仙缘入怀，俗念渐轻',
        '闭关一日，心境一新',
        '灵石微光，照见归途',
        '神识如网，万象入心',
        '符火初燃，邪祟自退',
        '道友同行，长路不孤',
        '灵禽过境，云气生祥',
        '月照丹炉，火候正好',
        '青山不语，妙法自传',
        '执念化尘，道心成玉',
        '仙路有阶，稳步登临',
        '灵泉洗心，杂念皆空',
        '天风拂袖，尘网自开',
        '一念护身，百劫可渡',
        '宝库有藏，机缘有门',
        '三界如棋，落子无悔',
        '阵纹微亮，万法归枢',
        '云阶在前，且行且悟',
        '心境如镜，照破虚妄',
        '灵草含露，丹途可期',
        '剑心未冷，道意常新',
        '天光入室，旧障自消',
        '万灵有应，善念有归',
        '秘境开门，勇者先行',
        '小世界中，别有乾坤',
        '宗门灯火，照拂归人',
        '修身养性，厚积薄发',
        '玄机一线，不可轻失',
        '心随云静，法随意成',
        '命数可推，道心自定',
        '灵舟泊岸，远行将启',
        '一页残卷，万般因果',
        '清露沾衣，晨修正好',
        '风雷未动，气象已成',
        '入定片刻，尘心尽洗',
        '踏月归来，袖有星辉',
        '天道酬勤，仙途酬心',
        '机缘如露，莫负晨光',
        '法印轻落，诸邪退避',
        '藏锋守拙，厚德载道',
        '云外有山，道外有道',
        '灵根未朽，前路仍长',
        '问心无愧，问道无惧',
        '一朝悟法，四海生风',
        '仙踪难觅，勤者可寻',
        '心火不灭，大道可期',
        '天地有常，修行有度',
        '玉露凝香，福至心灵',
        '云深不迷，灯明可归',
        '万法皆备，只待一念',
        '灵台一净，诸事皆明',
    ];
    let index = 0;
    const intervalMs = 4200;
    const transitionMs = 260;

    const swap = () => {
        if (document.hidden) return;
        slogan.classList.add('is-switching');
        window.setTimeout(() => {
            index = (index + 1) % slogans.length;
            slogan.textContent = slogans[index];
            slogan.classList.remove('is-switching');
        }, transitionMs);
    };

    window.setInterval(swap, intervalMs);
}

function mountProfileInventorySearchHistory() {
    const form = document.querySelector('[data-profile-inventory-search-form]');
    const input = document.querySelector('[data-profile-inventory-search-input]');
    const container = document.querySelector('[data-profile-inventory-search-history]');
    if (!form || !input || !container) return;

    const storageKey = 'profile-inventory-search-history';
    const maxItems = 12;
    const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim();

    const readHistory = () => {
        try {
            const parsed = JSON.parse(window.localStorage.getItem(storageKey) || '[]');
            if (!Array.isArray(parsed)) return [];
            return parsed.map(normalize).filter(Boolean).slice(0, maxItems);
        } catch (_error) {
            return [];
        }
    };

    const writeHistory = (items) => {
        try {
            window.localStorage.setItem(storageKey, JSON.stringify(items.slice(0, maxItems)));
        } catch (_error) {
            // Searching remains usable when local storage is unavailable.
        }
    };

    const render = (items = readHistory()) => {
        container.innerHTML = '';
        container.hidden = items.length === 0;
        items.forEach((query) => {
            const item = document.createElement('span');
            item.className = 'profile-search-history-item';

            const searchButton = document.createElement('button');
            searchButton.className = 'profile-search-history-query';
            searchButton.type = 'button';
            searchButton.textContent = query;
            searchButton.title = query;
            searchButton.addEventListener('click', () => {
                input.value = query;
                form.requestSubmit();
            });

            const removeButton = document.createElement('button');
            removeButton.className = 'profile-search-history-remove';
            removeButton.type = 'button';
            removeButton.textContent = '×';
            removeButton.setAttribute('aria-label', `删除搜索关键词：${query}`);
            removeButton.addEventListener('click', () => {
                const next = readHistory().filter((itemQuery) => itemQuery !== query);
                writeHistory(next);
                render(next);
            });

            item.append(searchButton, removeButton);
            container.appendChild(item);
        });
    };

    const save = (value) => {
        const query = normalize(value);
        if (!query) return;
        const next = [query, ...readHistory().filter((item) => item !== query)];
        writeHistory(next);
        render(next);
    };

    form.addEventListener('submit', () => save(input.value));
    const currentQuery = normalize(input.value);
    if (currentQuery) {
        save(currentQuery);
    } else {
        render();
    }
}

function mountAdminGlobalExecution() {
    const root = document.querySelector('[data-admin-execution-page]');
    if (!(root instanceof HTMLElement)) return;
    const statusUrl = root.dataset.statusUrl || '';
    const forms = Array.from(root.querySelectorAll('[data-admin-execution-form]'));
    const buttons = forms
        .map((form) => form.querySelector('button[type="submit"]'))
        .filter((button) => button instanceof HTMLButtonElement);
    const overlay = document.getElementById('global-loading-overlay');
    const message = document.getElementById('global-loading-message');
    let polling = false;
    let currentKind = root.dataset.activeKind || '';
    let pollDelayMs = 1000;
    let previousProgressKey = '';
    const maxPollDelayMs = 4000;

    root.querySelectorAll('[data-admin-execution-strategy-select]').forEach((select) => {
        if (!(select instanceof HTMLSelectElement)) return;
        const kind = select.dataset.adminExecutionStrategySelect || '';
        const input = root.querySelector(`[data-admin-execution-strategy-input="${kind}"]`);
        if (!(input instanceof HTMLInputElement)) return;
        const sync = () => { input.value = select.value; };
        select.addEventListener('change', sync);
        sync();
    });

    const setButtonsDisabled = (disabled) => {
        buttons.forEach((button) => {
            button.disabled = disabled;
        });
    };

    const renderCard = (card) => {
        if (!card || !card.kind) return;
        const cardRoot = root.querySelector(`[data-admin-execution-card="${card.kind}"]`);
        if (!(cardRoot instanceof HTMLElement)) return;

        const status = cardRoot.querySelector('[data-admin-execution-status]');
        if (status instanceof HTMLElement) {
            status.className = `admin-execution-status is-${card.status}`;
            status.textContent = card.status_label || '';
        }
        const summaryValues = {
            started_at: card.started_at || '—',
            success: card.counts?.success ?? 0,
            failed: card.counts?.failed ?? 0,
            skipped: card.counts?.skipped ?? 0,
        };
        Object.entries(summaryValues).forEach(([key, value]) => {
            const target = cardRoot.querySelector(`[data-admin-execution-summary="${key}"]`);
            if (target instanceof HTMLElement) target.textContent = String(value);
        });

        const report = cardRoot.querySelector('[data-admin-execution-report]');
        const reportSummary = cardRoot.querySelector('[data-admin-execution-report-summary]');
        const reportBody = cardRoot.querySelector('[data-admin-execution-report-body]');
        if (report instanceof HTMLDetailsElement && card.status === 'running') {
            report.open = true;
        }
        if (reportSummary instanceof HTMLElement) {
            reportSummary.textContent = `元神执行录（${card.done || 0}/${card.total || 0}）`;
        }
        if (!(reportBody instanceof HTMLElement)) return;

        const items = Array.isArray(card.items) ? card.items : [];
        if (items.length === 0) {
            const empty = document.createElement('p');
            empty.className = 'muted top-gap';
            empty.textContent = '暂无执行记录。';
            reportBody.replaceChildren(empty);
            return;
        }

        const table = document.createElement('div');
        table.className = 'admin-execution-report-table';
        const header = document.createElement('div');
        header.className = 'admin-execution-report-row is-header';
        ['元神', '结果', '奖励'].forEach((label) => {
            const cell = document.createElement('span');
            cell.textContent = label;
            header.appendChild(cell);
        });
        table.appendChild(header);
        items.forEach((item) => {
            const row = document.createElement('div');
            row.className = 'admin-execution-report-row';
            const name = document.createElement('strong');
            name.textContent = item.profile_name || '';
            const result = document.createElement('span');
            result.className = `admin-execution-result is-${item.status || 'queued'}`;
            result.textContent = item.status_label || '';
            const reward = document.createElement('span');
            reward.textContent = item.reward || '—';
            row.append(name, result, reward);
            table.appendChild(row);
        });
        reportBody.replaceChildren(table);
    };

    const progressKey = (state) => {
        const card = state.card || {};
        return JSON.stringify([
            state.active_kind || '',
            card.status || '',
            card.done || 0,
            Array.isArray(card.items)
                ? card.items.map((item) => [item.status, item.status_label, item.reward])
                : [],
        ]);
    };

    const updatePollDelay = (state) => {
        const nextProgressKey = progressKey(state);
        pollDelayMs = nextProgressKey === previousProgressKey
            ? Math.min(maxPollDelayMs, pollDelayMs + 1000)
            : 1000;
        previousProgressKey = nextProgressKey;
    };

    const poll = async () => {
        if (polling || !statusUrl) return;
        polling = true;
        try {
            while (true) {
                await new Promise((resolve) => window.setTimeout(resolve, pollDelayMs));
                await waitForDocumentVisible();
                const statusRequestUrl = new URL(statusUrl, window.location.href);
                if (currentKind) statusRequestUrl.searchParams.set('kind', currentKind);
                const response = await fetch(statusRequestUrl, {
                    credentials: 'same-origin',
                    headers: { Accept: 'application/json' },
                });
                if (!response.ok) throw new Error(`Status request failed: ${response.status}`);
                const state = await response.json();
                renderCard(state.card);
                if (message && state.loading_message) {
                    message.textContent = state.loading_message;
                }
                if (!state.active) {
                    root.dataset.active = '0';
                    root.dataset.activeKind = '';
                    hideGlobalLoading(overlay);
                    setButtonsDisabled(false);
                    return;
                }
                currentKind = state.active_kind || currentKind;
                root.dataset.active = '1';
                root.dataset.activeKind = currentKind;
                updatePollDelay(state);
            }
        } catch (_error) {
            hideGlobalLoading(overlay);
            setButtonsDisabled(false);
            window.alert('批量任务状态读取失败，请刷新页面后重试。');
        } finally {
            polling = false;
        }
    };

    const startPolling = async (state) => {
        currentKind = state.active_kind || state.card?.kind || currentKind;
        renderCard(state.card);
        root.dataset.active = state.active ? '1' : '0';
        root.dataset.activeKind = currentKind;
        if (!state.active) {
            hideGlobalLoading(overlay);
            setButtonsDisabled(false);
            return;
        }
        setButtonsDisabled(true);
        pollDelayMs = 1000;
        previousProgressKey = progressKey(state);
        await showGlobalLoading(
            overlay,
            message,
            state.loading_message || '正在执行全局任务',
        );
        poll();
    };

    forms.forEach((form) => {
        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const confirmMessage = form.dataset.confirmMessage || '';
            if (confirmMessage && !window.confirm(confirmMessage)) return;
            setButtonsDisabled(true);
            try {
                const response = await fetch(form.action, {
                    method: 'POST',
                    credentials: 'same-origin',
                    body: new FormData(form),
                    headers: {
                        Accept: 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                });
                const state = await response.json();
                if (!response.ok) {
                    throw new Error(state.detail || `Start request failed: ${response.status}`);
                }
                currentKind = form.dataset.adminExecutionKind || state.active_kind || '';
                await startPolling(state);
            } catch (error) {
                setButtonsDisabled(false);
                window.alert(error instanceof Error ? error.message : '全局任务启动失败。');
            }
        });
    });

    if (root.dataset.active === '1') {
        startPolling({
            active: true,
            active_kind: currentKind,
            loading_message: root.dataset.loadingMessage || '正在执行全局任务',
            card: null,
        });
    }
}

warmHealthCheck();
warmJadeLoadingAssets();
mountCountdowns();
mountGlobalLoadingForms();
mountPartialCardRefreshes();
mountNavigationTransitions();
mountTianxingRewardDateLookup();
mountGlobalConfirmDialogForms();
mountGlobalResultDialog();
mountThemeSwitcher();
mountBrandSloganCarousel();
mountProfileInventorySearchHistory();
mountAdminGlobalExecution();
