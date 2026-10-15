/* Billing is mounted only within the current account/team generation. */
(() => {
  'use strict';
  const panel = document.getElementById('billing-panel');
  let generation = 0;
  const node = (tag, text, cls) => {
    const n = document.createElement(tag);
    n.textContent = text == null ? '' : String(text);
    if (cls) n.className = cls;
    return n;
  };
  const zeroDecimal = new Set('BIF CLP DJF GNF JPY KMF KRW MGA PYG RWF VND VUV XAF XOF XPF'.split(' '));
  function priceLabel(price) {
    if (!price || !Number.isSafeInteger(price.amount) || price.amount <= 0 ||
        typeof price.currency !== 'string' || !/^[a-z]{3}$/.test(price.currency) || price.interval !== 'month') return null;
    const currency = price.currency.toUpperCase(), digits = zeroDecimal.has(currency) ? 0 : 2;
    try {
      return new Intl.NumberFormat('en', {style: 'currency', currency, minimumFractionDigits: digits,
        maximumFractionDigits: digits}).format(price.amount / (digits === 0 ? 1 : 100)) + ' / month';
    } catch (_) { return null; }
  }
  function destination(result, action) {
    const kind = result?.kind, raw = result?.url;
    if (!['checkout', 'portal'].includes(kind) || (action === 'portal' && kind !== 'portal') ||
        typeof raw !== 'string' || raw.length > 4096 || /[\x00-\x20\x7f\\]/.test(raw)) return null;
    const host = kind === 'checkout' ? 'checkout.stripe.com' : 'billing.stripe.com';
    // Compare the literal authority before URL parsing can normalize a dangerous spelling.
    const authority = /^https:\/\/([^/?#]+)(?:[/?#]|$)/.exec(raw)?.[1];
    if (authority !== host && authority !== host + ':443') return null;
    try {
      const url = new URL(raw);
      if (url.protocol !== 'https:' || url.hostname !== host || url.username || url.password ||
          (url.port && url.port !== '443') || (kind === 'portal' && raw.includes('#'))) return null;
      return raw; // Checkout's opaque provider fragment must survive unchanged.
    } catch (_) { return null; }
  }
  function dateLabel(value) {
    if (!Number.isSafeInteger(value) || value <= 0) return null;
    const date = new Date(value * 1000);
    if (!Number.isFinite(date.getTime())) return null;
    return date.toLocaleString('en', {year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'});
  }
  function safeError(error) {
    if (error.status === 401 || error.status === 403) return 'You do not have permission to manage billing. Ask a team owner.';
    if (error.status === 409) return 'Billing is already being updated. Please retry shortly.';
    return 'Billing is unavailable. Please retry shortly.';
  }
  function clear() {
    generation++;
    if (panel) {panel.hidden = true; panel.replaceChildren(); panel.setAttribute('aria-busy', 'false');}
  }
  async function load(context) {
    clear();
    if (!panel || !context.teamId) return;
    const mine = generation, current = () => mine === generation && context.isCurrent();
    const base = '/account/teams/' + encodeURIComponent(context.teamId) + '/billing';
    const header = node('div', '', 'billing-heading');
    const heading = node('h2', 'Plan & billing'); heading.id = 'billing-heading';
    header.append(node('p', 'TEAM CAPACITY / MONTHLY SUBSCRIPTION', 'eyebrow'), heading);
    const content = node('div', '', 'billing-content'), notice = node('p', '', 'billing-notice');
    notice.setAttribute('role', 'status'); notice.setAttribute('aria-live', 'polite');
    if (window.location.hash === '#billing-return') notice.textContent = 'Awaiting confirmation. Returning from checkout does not confirm payment; the server verifies your subscription.';
    const errorBox = node('p', '', 'error billing-error'); errorBox.setAttribute('role', 'alert');
    panel.append(header, notice, content, errorBox); panel.hidden = false;
    let busy = false, buttons = [];
    function setBusy(value) {
      if (!current()) return;
      busy = value; panel.setAttribute('aria-busy', String(value));
      for (const button of buttons) button.disabled = value;
    }
    async function getSummary() {
      if (!current()) return;
      const summary = await context.request(base);
      if (!current()) return;
      if (summary.team_id !== context.teamId) throw new Error('Invalid billing response');
      render(summary);
    }
    function actionButton(label, action, primary = false) {
      const button = node('button', label, primary ? 'primary' : ''); button.type = 'button';
      button.addEventListener('click', async () => {
        if (!current() || busy || context.role !== 'owner') return;
        setBusy(true); errorBox.textContent = '';
        try {
          const result = await context.request(base + '/' + action, {});
          if (!current()) return;
          if (action === 'sync') {
            await getSummary();
            if (current()) notice.textContent = 'Billing refreshed from the server.';
          } else {
            const url = destination(result, action);
            if (!url) {errorBox.textContent = 'Billing did not return a valid payment destination. Please retry or contact your deployment administrator.'; return;}
            if (current()) window.location.assign(url);
          }
        } catch (error) {if (current()) errorBox.textContent = safeError(error);}
        finally {setBusy(false);}
      });
      buttons.push(button); return button;
    }
    function render(summary) {
      if (!current()) return;
      content.replaceChildren(); buttons = [];
      const enabled = summary.enabled === true, owner = enabled && summary.can_manage === true && context.role === 'owner';
      const plan = summary.plan === 'team' && summary.paid === true ? 'Team' : enabled ? 'Free' : 'Unlimited';
      const overview = node('div', '', 'billing-overview');
      const planCard = node('div', '', 'billing-plan');
      planCard.append(node('p', 'CURRENT PLAN', 'eyebrow'), node('h3', plan, 'billing-plan-name'));
      const deployment = summary.mode === 'self-hosted' ? 'Self-hosted · unlimited team capacity' : enabled ? 'Cloud · monthly Team subscription' : 'Cloud · subscriptions are not enabled';
      planCard.append(node('p', deployment, 'muted'));
      if (!enabled) planCard.append(node('p', summary.mode === 'cloud' ? 'Subscriptions are not enabled for this deployment. Team capacity is unlimited.' : 'Your self-hosted deployment has unlimited members and projects.', 'billing-detail'));
      if (enabled) {
        const price = priceLabel(summary.price);
        planCard.append(node('p', price || 'Price unavailable', 'billing-price'));
        planCard.append(node('p', price ? 'Verified monthly Team price. Charged through Stripe.' : 'A verified monthly price is unavailable. Checkout is currently unavailable.', 'billing-detail'));
        if (owner && ['test', 'live'].includes(summary.billing?.provider_mode)) planCard.append(node('span', summary.billing.provider_mode === 'test' ? 'Test payments' : 'Live payments', 'billing-mode'));
      }
      const usage = node('div', '', 'billing-usage');
      for (const [key, label] of [['members', 'Active team members'], ['projects', 'Team projects']]) {
        const used = summary.usage?.[key], limit = summary.limits?.[key];
        const actual = Number.isSafeInteger(used) && used >= 0 ? String(used) : 'Unavailable';
        const maximum = limit === null ? 'unlimited' : Number.isSafeInteger(limit) && limit >= 0 ? String(limit) : 'unavailable';
        const item = node('div', '', 'billing-usage-item');
        item.append(node('p', label, 'muted'), node('p', actual + ' of ' + maximum, 'billing-usage-value'));
        if (summary.over_limit?.[key] === true) item.append(node('p', 'Over the current limit', 'billing-warning'));
        usage.append(item);
      }
      usage.append(node('p', 'Counts use active account members and projects bound to this team.', 'billing-detail'));
      overview.append(planCard, usage); content.append(overview);
      if (enabled) {
        const statusLabels = {unsubscribed:'No subscription',none:'No subscription',incomplete:'Payment incomplete',incomplete_expired:'Payment expired',trialing:'Trialing',active:'Active',past_due:'Past due',canceled:'Canceled',unpaid:'Unpaid',paused:'Paused'};
        const state = node('div', '', 'billing-state');
        state.append(node('p', 'Subscription status: ' + (statusLabels[summary.status] || 'Unavailable')));
        const paidUntil = summary.paid === true ? dateLabel(summary.paid_until) : null;
        if (paidUntil) state.append(node('p', 'Paid through: ' + paidUntil));
        if (summary.cancel_at_period_end === true) state.append(node('p', 'Cancellation scheduled at the end of the billing period.'));
        if (summary.risk_hold === true) state.append(node('p', 'Payment review is pending. Current limits apply.', 'billing-warning'));
        state.append(node('p', 'Last synced: ' + (dateLabel(summary.last_sync) || 'Not yet synced'), 'muted'));
        content.append(state);
        if (owner) {
          const actions = node('div', '', 'billing-actions');
          if (summary.checkout_available === true && priceLabel(summary.price)) actions.append(actionButton('Subscribe to Team', 'checkout', true));
          if (typeof summary.billing?.customer_id === 'string' && summary.billing.customer_id) actions.append(actionButton('Manage subscription', 'portal'));
          actions.append(actionButton('Sync billing', 'sync')); content.append(actions);
          if (summary.billing?.last_error) errorBox.textContent = 'The last billing update did not finish. Sync billing to retry.';
        } else content.append(node('p', 'A team owner manages subscription payments.', 'billing-detail'));
      }
      setBusy(busy);
    }
    content.append(node('p', 'Loading billing…', 'muted')); setBusy(true);
    try {await getSummary();}
    catch (error) {
      if (current()) {
        content.replaceChildren(); errorBox.textContent = safeError(error);
        const retry = node('button', 'Retry billing'); retry.type = 'button';
        retry.addEventListener('click', () => {if (current()) load(context);}); content.append(retry);
      }
    } finally {
      setBusy(false);
      if (current() && ['#billing', '#billing-return'].includes(window.location.hash)) panel.scrollIntoView({block: 'start'});
    }
  }
  window.CoopagentsBilling = {clear, load};
})();
