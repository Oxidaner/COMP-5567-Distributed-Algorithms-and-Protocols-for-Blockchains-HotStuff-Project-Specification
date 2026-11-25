import {signTransfer} from './signing.js';

const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let currentState = null;
let selectedBlock = 'B0';
let busy = false;
let requestNumber = 0;
let renderedRequest = 0;
let lastSignedRequest = null;

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
    return await api(path, typeof body === 'function' ? await body() : body);
  } catch (error) {
    $('error').textContent = error.message;
    $('error').hidden = false;
  } finally {
    busy = false;
    document.querySelectorAll('button').forEach(button => button.disabled = false);
    $('retry-transfer').disabled = !lastSignedRequest;
  }
}

function qcLabel(qc) { return `${qc.block_id} <small>v${qc.view}</small>`; }
function txLine(tx) {
  return `<span class="mono">${escapeHtml(tx.id)}</span><span>${escapeHtml(tx.sender)} → ${escapeHtml(tx.receiver)} <small>nonce ${escapeHtml(tx.nonce)}</small></span><strong>${tx.amount}</strong>`;
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
  $('accounts').innerHTML = Object.entries(state.accounts).map(([name, balance]) => `<div><span>${name}</span><strong>${balance}<small>units</small></strong><small>Next execution nonce ${state.nonces[name]}</small></div>`).join('');
  $('batch-limit').value = String(state.max_txs_per_block);
  $('mempool-count').textContent = state.mempool.length;
  $('mempool').innerHTML = state.mempool.length ? state.mempool.map(tx => `<div class="tx">${txLine(tx)}</div>`).join('') : '<p class="empty">Mempool is empty · Submit a transfer to begin</p>';
  const receipts = state.execution_receipts;
  $('receipt-count').textContent = receipts.length;
  $('receipts').innerHTML = receipts.length ? receipts.slice(-30).reverse().map(tx => `<div class="receipt"><div class="tx">${txLine(tx)}</div><small>${escapeHtml(tx.block_id)} / position ${tx.transaction_index} · </small><small class="${tx.status === 'rejected' ? 'fault' : 'commit'}">${tx.status === 'rejected' ? `Execution failed: ${escapeHtml(tx.error)}` : '✓ Committed · Executed'}</small></div>`).join('') : '<p class="empty">Waiting for a transaction block to commit</p>';
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
    if (data && button.dataset.action === 'reset') {
      lastSignedRequest = null;
      $('retry-transfer').disabled = true;
      $('tx-message').textContent = 'Reset complete · Balances 100 · Nonces 0';
    }
  });
});
$('double-proposal').addEventListener('click', () => {
  mutate('/api/attacks', async () => {
    const state = await api('/api/control/pause', {});
    return {kind: 'equivocation', node_id: state.leader_id};
  });
});
$('byzantine').addEventListener('change', event => mutate('/api/byzantine', {node_id: event.target.value ? Number(event.target.value) : null}));
$('blocks').addEventListener('click', event => {
  const block = event.target.closest('[data-block]');
  if (block) { selectedBlock = block.dataset.block; render(currentState); }
});
$('transfer-form').addEventListener('submit', async event => {
  event.preventDefault();
  const result = await mutate('/api/transactions', async () => {
    if (!crypto.subtle) throw new Error('Browser signing requires localhost or HTTPS and Ed25519 support.');
    const sender = $('sender').value;
    const receiver = $('receiver').value;
    const amount = Number($('amount').value);
    const state = await api('/api/state');
    let nonce = state.nonces[sender];
    const pending = new Set(state.mempool.filter(tx => tx.sender === sender).map(tx => tx.nonce));
    while (pending.has(nonce)) nonce += 1;
    lastSignedRequest = await signTransfer(sender, receiver, amount, nonce);
    return lastSignedRequest;
  });
  if (result) $('tx-message').textContent = `${result.transaction_id} signed and queued · Advance consensus to execute`;
});
$('retry-transfer').addEventListener('click', async () => {
  const result = await mutate('/api/transactions', lastSignedRequest);
  if (result) {
    const tx = result.state.transactions.find(tx => tx.id === result.transaction_id);
    $('tx-message').textContent = `${result.transaction_id} · ${tx.status} · Same signed request, no duplicate execution`;
  }
});
$('batch-limit').addEventListener('change', event => {
  mutate('/api/config/batch', {max_txs_per_block: Number(event.target.value)});
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

