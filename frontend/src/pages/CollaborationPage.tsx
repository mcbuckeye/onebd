import { FormEvent, useCallback, useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import {
  ExternalLink,
  Link2,
  MessageSquare,
  Plus,
  Send,
  Share2,
  Trash2,
  Users,
} from 'lucide-react';
import api from '../lib/api';
import { useAuth } from '../contexts/AuthContext';

type TeamRole = 'owner' | 'editor' | 'viewer';

interface TeamSummary {
  id: number;
  name: string;
  role: TeamRole;
  member_count: number;
  item_count: number;
}

interface TeamMember {
  id: number;
  name: string;
  email: string;
  role: TeamRole;
}

interface TeamDetail extends TeamSummary {
  members: TeamMember[];
}

interface SharedItem {
  id: number;
  resource_type: string;
  resource_id: string | null;
  title: string;
  resource_url: string | null;
  note: string | null;
  created_by: number;
  creator_name: string;
  created_at: string;
  comment_count: number;
}

interface TeamComment {
  id: number;
  author_id: number;
  author_name: string;
  body: string;
  created_at: string;
}

const RESOURCE_TYPES = [
  'deal', 'company', 'drug', 'filing', 'contract', 'search', 'briefing', 'other',
];

export default function CollaborationPage() {
  const { user } = useAuth();
  const [teams, setTeams] = useState<TeamSummary[]>([]);
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null);
  const [team, setTeam] = useState<TeamDetail | null>(null);
  const [items, setItems] = useState<SharedItem[]>([]);
  const [comments, setComments] = useState<Record<number, TeamComment[]>>({});
  const [commentDrafts, setCommentDrafts] = useState<Record<number, string>>({});
  const [newTeamName, setNewTeamName] = useState('');
  const [memberEmail, setMemberEmail] = useState('');
  const [memberRole, setMemberRole] = useState<'editor' | 'viewer'>('editor');
  const [shareForm, setShareForm] = useState({
    resource_type: 'deal',
    resource_id: '',
    title: '',
    resource_url: '',
    note: '',
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const loadTeams = useCallback(async (preferredId?: number) => {
    const response = await api.get('/collaboration/teams');
    const nextTeams = response.data as TeamSummary[];
    setTeams(nextTeams);
    setSelectedTeamId((current) => {
      const candidate = preferredId ?? current;
      if (candidate && nextTeams.some((entry) => entry.id === candidate)) return candidate;
      return nextTeams[0]?.id ?? null;
    });
  }, []);

  const loadTeam = useCallback(async (teamId: number) => {
    setLoading(true);
    setError('');
    try {
      const [teamResponse, itemResponse] = await Promise.all([
        api.get(`/collaboration/teams/${teamId}`),
        api.get(`/collaboration/teams/${teamId}/items`),
      ]);
      const nextItems = itemResponse.data as SharedItem[];
      setTeam(teamResponse.data);
      setItems(nextItems);
      const commentResults = await Promise.all(nextItems.map(async (item) => {
        const response = await api.get(`/collaboration/items/${item.id}/comments`);
        return [item.id, response.data as TeamComment[]] as const;
      }));
      setComments(Object.fromEntries(commentResults));
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load the team workspace');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTeams().catch((err) => {
      setError(err.response?.data?.detail || 'Failed to load teams');
      setLoading(false);
    });
  }, [loadTeams]);

  useEffect(() => {
    if (selectedTeamId) loadTeam(selectedTeamId);
    else {
      setTeam(null);
      setItems([]);
      setLoading(false);
    }
  }, [loadTeam, selectedTeamId]);

  const createTeam = async (event: FormEvent) => {
    event.preventDefault();
    if (!newTeamName.trim()) return;
    setSaving(true);
    setError('');
    try {
      const response = await api.post('/collaboration/teams', { name: newTeamName.trim() });
      setNewTeamName('');
      await loadTeams(response.data.id);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create team');
    } finally {
      setSaving(false);
    }
  };

  const addMember = async (event: FormEvent) => {
    event.preventDefault();
    if (!team || !memberEmail.trim()) return;
    setSaving(true);
    setError('');
    try {
      await api.post(`/collaboration/teams/${team.id}/members`, {
        email: memberEmail.trim(),
        role: memberRole,
      });
      setMemberEmail('');
      await Promise.all([loadTeam(team.id), loadTeams(team.id)]);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to add team member');
    } finally {
      setSaving(false);
    }
  };

  const removeMember = async (memberId: number) => {
    if (!team || !confirm('Remove this colleague from the team?')) return;
    try {
      await api.delete(`/collaboration/teams/${team.id}/members/${memberId}`);
      await Promise.all([loadTeam(team.id), loadTeams(team.id)]);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to remove team member');
    }
  };

  const shareItem = async (event: FormEvent) => {
    event.preventDefault();
    if (!team || !shareForm.title.trim()) return;
    setSaving(true);
    setError('');
    try {
      await api.post(`/collaboration/teams/${team.id}/items`, {
        ...shareForm,
        resource_id: shareForm.resource_id.trim() || null,
        resource_url: shareForm.resource_url.trim() || null,
        note: shareForm.note.trim() || null,
        title: shareForm.title.trim(),
      });
      setShareForm({ resource_type: 'deal', resource_id: '', title: '', resource_url: '', note: '' });
      await Promise.all([loadTeam(team.id), loadTeams(team.id)]);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to share item');
    } finally {
      setSaving(false);
    }
  };

  const deleteItem = async (itemId: number) => {
    if (!team || !confirm('Remove this shared item and its discussion?')) return;
    try {
      await api.delete(`/collaboration/items/${itemId}`);
      await Promise.all([loadTeam(team.id), loadTeams(team.id)]);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete shared item');
    }
  };

  const addComment = async (itemId: number) => {
    const body = commentDrafts[itemId]?.trim();
    if (!body || !team) return;
    try {
      await api.post(`/collaboration/items/${itemId}/comments`, { body });
      setCommentDrafts((current) => ({ ...current, [itemId]: '' }));
      await loadTeam(team.id);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to add comment');
    }
  };

  const deleteTeam = async () => {
    if (!team || !confirm(`Delete “${team.name}” and all shared discussion?`)) return;
    try {
      await api.delete(`/collaboration/teams/${team.id}`);
      setSelectedTeamId(null);
      await loadTeams();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete team');
    }
  };

  const canEdit = team?.role === 'owner' || team?.role === 'editor';

  return (
    <div className="mx-auto max-w-[1500px] p-4 sm:p-6">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-3 text-2xl font-bold text-slate-100">
            <Users className="h-7 w-7 text-blue-400" /> Team workspaces
          </h1>
          <p className="mt-1 text-sm text-slate-500">Share evidence, keep notes in context, and discuss records with colleagues.</p>
        </div>
        <form onSubmit={createTeam} className="flex gap-2">
          <input value={newTeamName} onChange={(event) => setNewTeamName(event.target.value)} placeholder="New team name" className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 outline-none focus:border-blue-500" />
          <button disabled={saving || !newTeamName.trim()} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-40">
            <Plus className="h-4 w-4" /> Create
          </button>
        </form>
      </div>

      {error && <div className="mb-5 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">{error}</div>}

      {teams.length === 0 && !loading ? (
        <div className="rounded-xl border border-dashed border-slate-700 p-14 text-center">
          <Users className="mx-auto mb-3 h-10 w-10 text-slate-700" />
          <p className="text-slate-400">Create a team workspace to begin sharing research.</p>
        </div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[240px_minmax(0,1fr)_300px]">
          <aside className="rounded-xl border border-slate-800 bg-slate-900 p-3">
            <p className="mb-2 px-2 text-xs font-semibold uppercase tracking-wide text-slate-600">Your teams</p>
            <div className="space-y-1">
              {teams.map((entry) => (
                <button key={entry.id} type="button" onClick={() => setSelectedTeamId(entry.id)} className={`w-full rounded-lg p-3 text-left ${selectedTeamId === entry.id ? 'bg-blue-500/15 text-blue-300' : 'text-slate-400 hover:bg-slate-800'}`}>
                  <span className="block truncate text-sm font-medium">{entry.name}</span>
                  <span className="mt-1 block text-[11px] text-slate-600">{entry.member_count} members · {entry.item_count} items · {entry.role}</span>
                </button>
              ))}
            </div>
          </aside>

          <main className="min-w-0 space-y-4">
            {loading && <div className="h-40 animate-pulse rounded-xl bg-slate-900" />}
            {!loading && team && (
              <>
                <div className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900 p-4">
                  <div>
                    <h2 className="text-xl font-semibold text-slate-100">{team.name}</h2>
                    <p className="mt-1 text-xs text-slate-500">Your role: {team.role}</p>
                  </div>
                  {team.role === 'owner' && <button type="button" onClick={deleteTeam} className="rounded p-2 text-slate-600 hover:bg-red-500/10 hover:text-red-400"><Trash2 className="h-4 w-4" /></button>}
                </div>

                {canEdit && (
                  <form onSubmit={shareItem} className="rounded-xl border border-slate-800 bg-slate-900 p-4">
                    <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-300"><Share2 className="h-4 w-4" /> Share evidence</h3>
                    <div className="grid gap-3 sm:grid-cols-[150px_1fr]">
                      <select value={shareForm.resource_type} onChange={(event) => setShareForm({ ...shareForm, resource_type: event.target.value })} className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-300">
                        {RESOURCE_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
                      </select>
                      <input required value={shareForm.title} onChange={(event) => setShareForm({ ...shareForm, title: event.target.value })} placeholder="Title" className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 outline-none focus:border-blue-500" />
                      <input value={shareForm.resource_id} onChange={(event) => setShareForm({ ...shareForm, resource_id: event.target.value })} placeholder="Record ID (optional)" className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 outline-none focus:border-blue-500" />
                      <input value={shareForm.resource_url} onChange={(event) => setShareForm({ ...shareForm, resource_url: event.target.value })} placeholder="OneBD or source URL (optional)" className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 outline-none focus:border-blue-500" />
                    </div>
                    <textarea value={shareForm.note} onChange={(event) => setShareForm({ ...shareForm, note: event.target.value })} placeholder="Why this matters…" rows={2} className="mt-3 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 outline-none focus:border-blue-500" />
                    <button disabled={saving} className="mt-3 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-40">Share with team</button>
                  </form>
                )}

                {items.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-slate-700 p-12 text-center text-sm text-slate-500">No evidence has been shared with this team yet.</div>
                ) : items.map((item) => (
                  <article key={item.id} className="rounded-xl border border-slate-800 bg-slate-900 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="mb-1 flex items-center gap-2">
                          <span className="rounded bg-slate-800 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-500">{item.resource_type}</span>
                          {item.resource_id && <span className="font-mono text-[10px] text-slate-600">#{item.resource_id}</span>}
                        </div>
                        <h3 className="text-base font-semibold text-slate-200">{item.title}</h3>
                        <p className="mt-1 text-[11px] text-slate-600">Shared by {item.creator_name} · {new Date(item.created_at).toLocaleString()}</p>
                      </div>
                      {(team.role === 'owner' || item.created_by === user?.id) && <button type="button" onClick={() => deleteItem(item.id)} className="rounded p-1.5 text-slate-600 hover:bg-red-500/10 hover:text-red-400"><Trash2 className="h-4 w-4" /></button>}
                    </div>
                    {item.note && <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-400">{item.note}</p>}
                    {item.resource_url && (
                      item.resource_url.startsWith('/')
                        ? <RouterLink to={item.resource_url} className="mt-3 inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"><Link2 className="h-3.5 w-3.5" /> Open in OneBD</RouterLink>
                        : <a href={item.resource_url} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"><ExternalLink className="h-3.5 w-3.5" /> Open source</a>
                    )}
                    <div className="mt-4 border-t border-slate-800 pt-3">
                      <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-500"><MessageSquare className="h-3.5 w-3.5" /> Discussion ({comments[item.id]?.length || 0})</p>
                      <div className="space-y-2">
                        {(comments[item.id] || []).map((comment) => (
                          <div key={comment.id} className="rounded-lg bg-slate-950/60 p-2.5 text-sm text-slate-400">
                            <p className="whitespace-pre-wrap">{comment.body}</p>
                            <p className="mt-1 text-[10px] text-slate-600">{comment.author_name} · {new Date(comment.created_at).toLocaleString()}</p>
                          </div>
                        ))}
                      </div>
                      <div className="mt-2 flex gap-2">
                        <input value={commentDrafts[item.id] || ''} onChange={(event) => setCommentDrafts({ ...commentDrafts, [item.id]: event.target.value })} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); addComment(item.id); } }} placeholder="Add a comment" className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 outline-none focus:border-blue-500" />
                        <button type="button" onClick={() => addComment(item.id)} className="rounded-lg bg-slate-800 p-2 text-slate-400 hover:text-blue-300"><Send className="h-4 w-4" /></button>
                      </div>
                    </div>
                  </article>
                ))}
              </>
            )}
          </main>

          <aside className="space-y-4">
            {team && (
              <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
                <h3 className="mb-3 text-sm font-semibold text-slate-300">Members</h3>
                <div className="space-y-2">
                  {team.members.map((member) => (
                    <div key={member.id} className="flex items-center justify-between gap-2 rounded-lg bg-slate-800/60 p-2.5">
                      <div className="min-w-0">
                        <p className="truncate text-xs font-medium text-slate-300">{member.name}</p>
                        <p className="truncate text-[10px] text-slate-600">{member.email} · {member.role}</p>
                      </div>
                      {team.role === 'owner' && member.role !== 'owner' && <button type="button" onClick={() => removeMember(member.id)} className="text-slate-600 hover:text-red-400"><Trash2 className="h-3.5 w-3.5" /></button>}
                    </div>
                  ))}
                </div>
                {team.role === 'owner' && (
                  <form onSubmit={addMember} className="mt-4 space-y-2 border-t border-slate-800 pt-4">
                    <p className="text-xs text-slate-500">Add an existing account</p>
                    <input type="email" required value={memberEmail} onChange={(event) => setMemberEmail(event.target.value)} placeholder="colleague@company.com" className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-slate-200 outline-none focus:border-blue-500" />
                    <div className="flex gap-2">
                      <select value={memberRole} onChange={(event) => setMemberRole(event.target.value as 'editor' | 'viewer')} className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-800 px-2 py-2 text-xs text-slate-300"><option value="editor">Editor</option><option value="viewer">Viewer</option></select>
                      <button disabled={saving} className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium hover:bg-blue-500 disabled:opacity-40">Add</button>
                    </div>
                  </form>
                )}
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
