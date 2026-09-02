/**
 * COS-092: JWT auth for e2e — COS-085 closed the legacy opaque-bearer
 * contract (only `ey...` tokens with a payload segment are accepted).
 * Signature is not verified on the deps layer (COS-031 contract), so a
 * locally minted unsigned JWT is the honest e2e credential.
 */
export function mintJwt(sub: string, roles: string[] = [], isAdmin = false): string {
  const b64u = (o: object) =>
    btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const claims: Record<string, unknown> = { sub, roles };
  if (isAdmin) claims.is_admin = true;
  return `${b64u({ alg: 'none', typ: 'JWT' })}.${b64u(claims)}.e2e`;
}

/** Fixed V1 recipient contract ('operator') with ops capabilities. */
export function operatorJwt(): string {
  return mintJwt('operator', ['admin_sec'], true);
}

/** Second principal for identity-separation checks (plain USER). */
export function viewerJwt(): string {
  return mintJwt('viewer');
}
