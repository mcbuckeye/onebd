import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Check,
  Copy,
  KeyRound,
  Loader2,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  X,
} from 'lucide-react';
import api from '../lib/api';

type AccessMode = 'key_required' | 'authenticated' | 'open';

interface ApiCredential {
  id: number;
  name: string;
  key_prefix: string;
  scopes: string[];
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
  last_used_path: string | null;
  use_count: number;
}

interface DataAccessPolicy {
  access_mode: AccessMode;
  enforce_scopes: boolean;
  allow_self_registration: boolean;
  protect_existing_api: boolean;
  disabled_datasets: string[];
  updated_at?: string;
}

interface PolicyResponse {
  policy: DataAccessPolicy;
  allowed_access_modes: AccessMode[];
  available_datasets: string[];
  license_metadata_is_advisory: boolean;
}

interface NewCredential extends ApiCredential {
  api_key: string;
}

const MODE_COPY: Record<AccessMode, { label: string; description: string }> = {
  key_required: {
    label: 'API key required',
    description: 'Only a valid OneBD API key can use the colleague API or MCP.',
  },
  authenticated: {
    label: 'Key or signed-in user',
    description: 'Allow API keys and active OneBD user sessions.',
  },
  open: {
    label: 'Open access',
    description: 'Allow anonymous read access to enabled versioned datasets.',
  },
};

const LABELS: Record<string, string> = {
  'data:read': 'All data (umbrella)',
  'catalog:read': 'Catalog',
  'deals:read': 'Deals',
  'companies:read': 'Companies',
  'drugs:read': 'Drugs',
  'trials:read': 'Clinical trials',
  'biology:read': 'Biology',
  'sources:read': 'Source status',
  catalog: 'Catalog',
  cortellis_deals: 'Cortellis deals',
  integrated_companies: 'Integrated companies',
  integrated_drugs: 'Integrated drugs',
  sec_edgar: 'SEC EDGAR',
  clinicaltrials_gov: 'ClinicalTrials.gov',
  public_biology: 'Public biology',
  source_status: 'Source status',
};

function displayName(value: string) {
  return LABELS[value] || value.replace(/_/g, ' ');
}

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : 'Never';
}

function Toggle({
  checked,
  onChange,
  title,
  description,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  title: string;
  description: string;
}) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4 rounded-lg border border-slate-800 bg-slate-950/40 p-4">
      <span>
        <span className="block text-sm font-medium text-slate-200">{title}</span>
        <span className="mt-1 block text-xs leading-5 text-slate-500">{description}</span>
      </span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-1 h-4 w-4 rounded border-slate-600 bg-slate-800 text-blue-600"
      />
    </label>
  );
}

export default function AdminApiAccessPanel() {
  const [credentials, setCredentials] = useState<ApiCredential[]>([]);
  const [allowedScopes, setAllowedScopes] = useState<string[]>([]);
  const [policyResponse, setPolicyResponse] = useState<PolicyResponse | null>(null);
  const [policy, setPolicy] = useState<DataAccessPolicy | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [name, setName] = useState('');
  const [expiresAt, setExpiresAt] = useState('');
  const [selectedScopes, setSelectedScopes] = useState<string[]>(['data:read']);
  const [newCredential, setNewCredential] = useState<NewCredential | null>(null);
  const [copied, setCopied] = useState(false);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const [credentialsResponse, policyResult] = await Promise.all([
        api.get('/admin/api-credentials'),
        api.get('/admin/data-access-policy'),
      ]);
      setCredentials(credentialsResponse.data.credentials);
      setAllowedScopes(credentialsResponse.data.allowed_scopes);
      setPolicyResponse(policyResult.data);
      setPolicy(policyResult.data.policy);
    } catch (requestError: any) {
      setError(requestError.response?.data?.detail || 'Failed to load API access controls');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const activeCredentialCount = useMemo(
    () => credentials.filter((credential) => (
      !credential.revoked_at
      && (!credential.expires_at || new Date(credential.expires_at) > new Date())
    )).length,
    [credentials],
  );

  const savePolicy = async () => {
    if (!policy) return;
    if (
      policy.access_mode === 'open'
      && !confirm('Open mode permits anonymous access to every enabled versioned dataset. Continue?')
    ) return;
    if (
      policy.protect_existing_api
      && policy.access_mode === 'key_required'
      && !confirm('Protecting existing routes in key-required mode can prevent the signed-in web UI from reading data unless it also supplies an API key. Continue?')
    ) return;

    setSavingPolicy(true);
    setError('');
    setMessage('');
    try {
      const response = await api.put('/admin/data-access-policy', policy);
      setPolicy(response.data);
      setPolicyResponse((current) => current ? { ...current, policy: response.data } : current);
      setMessage('Access policy saved and effective immediately.');
    } catch (requestError: any) {
      setError(requestError.response?.data?.detail || 'Failed to save access policy');
    } finally {
      setSavingPolicy(false);
    }
  };

  const createCredential = async (event: React.FormEvent) => {
    event.preventDefault();
    setCreating(true);
    setError('');
    setMessage('');
    try {
      const response = await api.post('/admin/api-credentials', {
        name,
        scopes: selectedScopes,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      });
      setNewCredential(response.data);
      setCopied(false);
      setName('');
      setExpiresAt('');
      setSelectedScopes(['data:read']);
      await load();
    } catch (requestError: any) {
      setError(requestError.response?.data?.detail || 'Failed to issue API key');
    } finally {
      setCreating(false);
    }
  };

  const revokeCredential = async (credential: ApiCredential) => {
    if (!confirm(`Revoke “${credential.name}”? Existing API and MCP clients using it will stop immediately.`)) return;
    setError('');
    setMessage('');
    try {
      await api.delete(`/admin/api-credentials/${credential.id}`);
      setMessage(`Revoked ${credential.name}.`);
      await load();
    } catch (requestError: any) {
      setError(requestError.response?.data?.detail || 'Failed to revoke API key');
    }
  };

  const copyKey = async () => {
    if (!newCredential) return;
    try {
      await navigator.clipboard.writeText(newCredential.api_key);
      setCopied(true);
    } catch {
      setError('Clipboard access was denied. Select and copy the key manually before dismissing it.');
    }
  };

  if (loading && !policy) {
    return (
      <div className="flex items-center justify-center rounded-xl border border-slate-800 bg-slate-900 py-16 text-slate-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading access controls...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
        </div>
      )}
      {message && (
        <div className="flex items-start gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-300">
          <Check className="mt-0.5 h-4 w-4 shrink-0" /> {message}
        </div>
      )}

      {newCredential && (
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="font-semibold text-amber-200">Copy this API key now</h3>
              <p className="mt-1 text-xs text-amber-100/70">It is returned once and cannot be recovered later.</p>
            </div>
            <button onClick={() => setNewCredential(null)} aria-label="Dismiss API key" className="text-amber-200/70 hover:text-amber-100">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="mt-4 flex gap-2">
            <code className="min-w-0 flex-1 overflow-x-auto rounded-lg bg-slate-950 px-3 py-2 text-xs text-amber-100">{newCredential.api_key}</code>
            <button onClick={copyKey} className="inline-flex items-center gap-2 rounded-lg bg-amber-500 px-3 py-2 text-sm font-medium text-slate-950 hover:bg-amber-400">
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>
      )}

      {policy && policyResponse && (
        <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-100">
                <ShieldCheck className="h-5 w-5 text-blue-400" /> Runtime access policy
              </h2>
              <p className="mt-1 max-w-3xl text-sm text-slate-500">
                You control technical enforcement. License labels remain advisory documentation and never override these switches.
              </p>
            </div>
            <span className="rounded-full border border-blue-500/30 bg-blue-500/10 px-3 py-1 text-xs text-blue-300">
              {policyResponse.license_metadata_is_advisory ? 'License metadata: advisory' : 'License enforcement active'}
            </span>
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-3">
            {policyResponse.allowed_access_modes.map((mode) => (
              <label key={mode} className={`cursor-pointer rounded-lg border p-4 ${policy.access_mode === mode ? 'border-blue-500 bg-blue-500/10' : 'border-slate-800 bg-slate-950/40'}`}>
                <input
                  type="radio"
                  name="access-mode"
                  value={mode}
                  checked={policy.access_mode === mode}
                  onChange={() => setPolicy({ ...policy, access_mode: mode })}
                  className="sr-only"
                />
                <span className="block text-sm font-medium text-slate-200">{MODE_COPY[mode].label}</span>
                <span className="mt-1 block text-xs leading-5 text-slate-500">{MODE_COPY[mode].description}</span>
              </label>
            ))}
          </div>

          <div className="mt-5 grid gap-3 lg:grid-cols-3">
            <Toggle
              checked={policy.enforce_scopes}
              onChange={(checked) => setPolicy({ ...policy, enforce_scopes: checked })}
              title="Enforce key scopes"
              description="Require the matching dataset scope, or the data:read umbrella scope."
            />
            <Toggle
              checked={policy.allow_self_registration}
              onChange={(checked) => setPolicy({ ...policy, allow_self_registration: checked })}
              title="Allow self-registration"
              description="Let new users create analyst accounts from the registration endpoint."
            />
            <Toggle
              checked={policy.protect_existing_api}
              onChange={(checked) => setPolicy({ ...policy, protect_existing_api: checked })}
              title="Protect existing app API"
              description="Extend the selected mode to legacy application data routes. Login, admin, and health stay reachable."
            />
          </div>

          <div className="mt-5">
            <h3 className="text-sm font-medium text-slate-200">Dataset switches</h3>
            <p className="mt-1 text-xs text-slate-500">Checked datasets are available. Turn one off to block it immediately in the colleague API and MCP.</p>
            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {policyResponse.available_datasets.map((dataset) => {
                const enabled = !policy.disabled_datasets.includes(dataset);
                return (
                  <label key={dataset} className="flex cursor-pointer items-center gap-2 rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm text-slate-300">
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={(event) => setPolicy({
                        ...policy,
                        disabled_datasets: event.target.checked
                          ? policy.disabled_datasets.filter((item) => item !== dataset)
                          : [...policy.disabled_datasets, dataset],
                      })}
                      className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-blue-600"
                    />
                    {displayName(dataset)}
                  </label>
                );
              })}
            </div>
          </div>

          <div className="mt-5 flex items-center justify-between border-t border-slate-800 pt-4">
            <p className="text-xs text-slate-600">Changes apply to new requests immediately and are audit logged.</p>
            <button onClick={savePolicy} disabled={savingPolicy} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-50">
              {savingPolicy && <Loader2 className="h-4 w-4 animate-spin" />} Save policy
            </button>
          </div>
        </section>
      )}

      <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-100">
              <KeyRound className="h-5 w-5 text-blue-400" /> API and MCP keys
            </h2>
            <p className="mt-1 text-sm text-slate-500">{activeCredentialCount} active key{activeCredentialCount === 1 ? '' : 's'}; plaintext is shown once.</p>
          </div>
          <button onClick={load} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-50">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </button>
        </div>

        <form onSubmit={createCredential} className="mt-5 rounded-lg border border-slate-800 bg-slate-950/40 p-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-slate-400">Key name</label>
              <input value={name} onChange={(event) => setName(event.target.value)} required maxLength={200} placeholder="BD team or analyst name" className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 focus:border-blue-500 focus:outline-none" />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-slate-400">Expiry (optional)</label>
              <input type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 focus:border-blue-500 focus:outline-none" />
            </div>
          </div>
          <div className="mt-4">
            <label className="mb-2 block text-xs font-medium text-slate-400">Scopes</label>
            <div className="flex flex-wrap gap-2">
              {allowedScopes.map((scope) => (
                <label key={scope} className={`cursor-pointer rounded-full border px-3 py-1.5 text-xs ${selectedScopes.includes(scope) ? 'border-blue-500/50 bg-blue-500/15 text-blue-300' : 'border-slate-700 text-slate-400'}`}>
                  <input
                    type="checkbox"
                    checked={selectedScopes.includes(scope)}
                    onChange={(event) => setSelectedScopes(event.target.checked ? [...selectedScopes, scope] : selectedScopes.filter((item) => item !== scope))}
                    className="sr-only"
                  />
                  {displayName(scope)}
                </label>
              ))}
            </div>
          </div>
          <div className="mt-4 flex justify-end">
            <button type="submit" disabled={creating || !name.trim()} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-50">
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Issue key
            </button>
          </div>
        </form>

        <div className="mt-5 overflow-x-auto rounded-lg border border-slate-800">
          <table className="w-full min-w-[900px]">
            <thead className="bg-slate-800/50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Name / prefix</th>
                <th className="px-4 py-3">Scopes</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Last used</th>
                <th className="px-4 py-3">Uses</th>
                <th className="px-4 py-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {credentials.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-sm text-slate-500">No API keys have been issued.</td></tr>
              ) : credentials.map((credential) => {
                const expired = Boolean(credential.expires_at && new Date(credential.expires_at) <= new Date());
                const active = !credential.revoked_at && !expired;
                return (
                  <tr key={credential.id} className="text-sm">
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-200">{credential.name}</div>
                      <code className="text-xs text-slate-600">onebd_{credential.key_prefix}_...</code>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-400">{credential.scopes.map(displayName).join(', ') || 'No scopes'}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2 py-1 text-xs ${active ? 'bg-emerald-500/15 text-emerald-300' : 'bg-slate-700 text-slate-400'}`}>
                        {credential.revoked_at ? 'Revoked' : expired ? 'Expired' : 'Active'}
                      </span>
                      {credential.expires_at && <div className="mt-1 text-[11px] text-slate-600">Expires {formatDate(credential.expires_at)}</div>}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-400">
                      <div>{formatDate(credential.last_used_at)}</div>
                      {credential.last_used_path && <code className="mt-1 block max-w-[220px] truncate text-slate-600">{credential.last_used_path}</code>}
                    </td>
                    <td className="px-4 py-3 text-slate-400">{credential.use_count.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right">
                      {active && (
                        <button onClick={() => revokeCredential(credential)} className="inline-flex items-center gap-1 text-xs text-red-400 hover:text-red-300">
                          <Trash2 className="h-3.5 w-3.5" /> Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
