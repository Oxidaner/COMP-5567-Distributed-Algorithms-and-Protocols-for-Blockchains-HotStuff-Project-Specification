const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let currentState = null;
let selectedBlock = 'B0';
let busy = false;
let requestNumber = 0;
let renderedRequest = 0;

async function api(path, body) {
  const number = ++requestNumber;
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : 'Invalid input. Check the accounts and enter a whole-number amount.';
    throw new Error(detail);
  }
  if (number >= renderedRequest) {
    renderedRequest = number;
    render(data.state || data);
  }
  $('connection').textContent = 'Connected';
  $('connection-dot').classList.add('online');
  return data;
}

async function mutate(path, body = {}) {
  if (busy) return;
  busy = true;
  $('error').hidden = true;
  document.querySelectorAll('button').forEach(button => button.disabled = true);
  try {
    return await api(path, body);
  } catch (error) {
    $('error').textContent = error.message;
    $('error').hidden = false;
  } finally {
    busy = false;
    document.querySelectorAll('button').forEach(button => button.disabled = false);
  }
}

function qcLabel(qc) { return `${qc.block_id} <small>v${qc.view}</small>`; }
function txLine(tx) {
  return `<span class="mono">${escapeHtml(tx.id)}</span><span>${escapeHtml(tx.sender)} → ${escapeHtml(tx.receiver)}</span><strong>${tx.amount}</strong>`;
}

function render(state) {
  currentState = state;
  $('view').textContent = String(state.view).padStart(2, '0');
  $('leader').textContent = `N${state.leader_id}`;
  $('running').textContent = `${state.running ? 'RUNNING' : 'PAUSED'} · STEP ${state.steps}`;
  $('phase').textContent = state.phase;
  $('consistency').textContent = state.consistent ? 'Live nodes agree' : 'No live nodes / sync pending';
  $('consistency').classList.toggle('warning', !state.consistent);
  const byzantine = state.nodes.find(n => n.withhold_vote);
  $('byzantine').value = byzantine ? byzantine.id : '';
  $('nodes').innerHTML = state.nodes.map(node => `
    <article class="node ${node.crashed ? 'crashed' : node.role === 'Leader' ? 'leader-node' : ''}">
      <div class="node-top"><h3><span class="node-icon">N${node.id}</span>Node ${node.id}</h3><span class="role">${node.crashed ? 'CRASHED' : node.role.toUpperCase()}</span></div>
      <div class="node-view">${String(node.view).padStart(2, '0')}<small>VIEW${node.crashed ? ' · FROZEN' : ''}</small></div>
      <dl><div><dt>HighQC</dt><dd>${qcLabel(node.high_qc)}</dd></div><div><dt>LockedQC</dt><dd>${qcLabel(node.locked_qc)}</dd></div><div><dt>Latest block</dt><dd>${node.latest_block}</dd></div><div><dt>Commit block</dt><dd class="commit">${node.committed_blocks.at(-1)}</dd></div></dl>
      <div class="node-balances">${Object.entries(node.accounts).map(([name, value]) => `${name} <b>${value}</b>`).join(' · ')}</div>
      <div class="node-foot ${node.withhold_vote ? 'fault' : ''}">${node.crashed ? 'Offline · No messages sent or received' : node.withhold_vote ? 'Byzantine · No votes, state still synced' : '● Online · Participating in consensus'}</div>
    </article>`).join('');
  $('block-count').textContent = `${state.blocks.length} blocks · ${state.committed_chain.length} committed`;
  if (!state.blocks.some(b => b.id === selectedBlock)) selectedBlock = 'B0';
  $('blocks').innerHTML = state.blocks.map(block => `
    <button class="block ${block.committed ? 'committed' : block.certificate ? 'certified' : 'pending'} ${block.id === selectedBlock ? 'selected' : ''}" data-block="${block.id}" aria-pressed="${block.id === selectedBlock}">
      <span>${block.committed ? 'COMMITTED' : block.certificate ? 'CERTIFIED' : 'PROPOSED'}</span><strong>${block.id}</strong><small>View ${block.view} · ${block.transactions.length} tx</small><small>parent ${block.parent_id || '—'}</small>
    </button>`).join('');
  $('committed-chain').textContent = state.committed_chain.join(' → ');
  renderBlock();
  $('accounts').innerHTML = Object.entries(state.accounts).map(([name, balance]) => `<div><span>${name}</span><strong>${balance}<small>units</small></strong></div>`).join('');
  $('mempool-count').textContent = state.mempool.length;
  $('mempool').innerHTML = state.mempool.length ? state.mempool.map(tx => `<div class="tx">${txLine(tx)}</div>`).join('') : '<p class="empty">Mempool is empty · Submit a transfer to begin</p>';
  const receipts = state.transactions.filter(tx => tx.status !== 'pending');
  $('receipt-count').textContent = receipts.length;
  $('receipts').innerHTML = receipts.length ? receipts.slice(-30).reverse().map(tx => `<div class="receipt"><div class="tx">${txLine(tx)}</div><small class="${tx.status === 'rejected' ? 'fault' : 'commit'}">${tx.status === 'rejected' ? `Execution failed: ${escapeHtml(tx.error)}` : '✓ Committed · Executed'}</small></div>`).join('') : '<p class="empty">Waiting for a transaction block to commit</p>';
  $('event-count').textContent = `Latest ${Math.min(state.logs.length, 100)} events · Newest first`;
  $('logs').innerHTML = state.logs.slice(-100).reverse().map(log => `<div class="log ${log.kind}"><div class="log-meta"><span>STEP ${String(log.step).padStart(3, '0')}</span><span>VIEW ${log.view} · ${log.kind.toUpperCase()}</span></div><p>${escapeHtml(log.message)}</p></div>`).join('');
}

function renderBlock() {
  const block = currentState.blocks.find(b => b.id === selectedBlock);
  if (!block) return;
  const voters = qc => qc ? qc.voters.map(id => `N${id}`).join(', ') : '—';
  $('block-detail').innerHTML = `
    <div class="detail-header"><strong>${block.id} / Block detail</strong><span class="${block.committed ? 'commit' : ''}">${block.committed ? 'Committed' : 'Uncommitted'}</span></div>
    <dl><div><dt>Parent / View / Leader</dt><dd>${block.parent_id || '—'} / ${block.view} / ${block.proposer ? `N${block.proposer}` : 'Genesis'}</dd></div>
    <div><dt>Parent QC (proposal.qc)</dt><dd>${block.qc ? `${block.qc.block_id} · voters ${voters(block.qc)}` : 'Genesis · No parent'}</dd></div>
    <div><dt>Block QC voters</dt><dd>${block.certificate ? voters(block.certificate) : `Not formed · Votes ${block.votes.length}/3`}</dd></div></dl>
    <div class="detail-transactions">${block.transactions.length ? block.transactions.map(tx => `<div class="tx">${txLine(tx)}</div>`).join('') : 'Empty block · Advances consensus'}</div>`;
}

document.querySelectorAll('[data-action]').forEach(button => {
  button.addEventListener('click', async () => {
    const data = await mutate(`/api/control/${button.dataset.action}`);
    if (data && button.dataset.action === 'reset') $('tx-message').textContent = 'Reset complete · All balances restored to 100';
  });
});
$('byzantine').addEventListener('change', event => mutate('/api/byzantine', {node_id: event.target.value ? Number(event.target.value) : null}));
$('blocks').addEventListener('click', event => {
  const block = event.target.closest('[data-block]');
  if (block) { selectedBlock = block.dataset.block; render(currentState); }
});
$('transfer-form').addEventListener('submit', async event => {
  event.preventDefault();
  const result = await mutate('/api/transactions', {sender: $('sender').value, receiver: $('receiver').value, amount: Number($('amount').value)});
  if (result) $('tx-message').textContent = `${result.transaction_id} entered the mempool · Click Start or Next Step to advance to commit`;
});

async function poll() {
  if (!busy) {
    try { await api('/api/state'); }
    catch (_) {
      $('connection').textContent = 'Disconnected · Reconnecting';
      $('connection-dot').classList.remove('online');
    }
  }
  setTimeout(poll, 400);
}
poll();

