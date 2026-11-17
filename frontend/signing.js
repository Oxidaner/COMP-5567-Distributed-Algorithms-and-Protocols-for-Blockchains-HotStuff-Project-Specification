// Public classroom fixtures match backend/blockchain.py; signing stays in the client.
export async function signTransfer(sender, receiver, amount, nonce) {
  const encoder = new TextEncoder();
  const seed = new Uint8Array(await crypto.subtle.digest(
    'SHA-256', encoder.encode(`COMP5567 classroom key: ${sender}`)
  ));
  // RFC 8410 PKCS#8 wrapper for a 32-byte Ed25519 private seed.
  const pkcs8 = new Uint8Array([
    0x30, 0x2e, 0x02, 0x01, 0x00, 0x30, 0x05, 0x06,
    0x03, 0x2b, 0x65, 0x70, 0x04, 0x22, 0x04, 0x20, ...seed
  ]);
  const key = await crypto.subtle.importKey('pkcs8', pkcs8, 'Ed25519', false, ['sign']);
  const payload = encoder.encode(JSON.stringify({
    amount, chain: 'COMP5567-HotStuff', nonce, receiver, sender
  }));
  const signature = new Uint8Array(await crypto.subtle.sign('Ed25519', key, payload));
  return {
    sender, receiver, amount, nonce,
    signature: Array.from(signature, byte => byte.toString(16).padStart(2, '0')).join('')
  };
}
