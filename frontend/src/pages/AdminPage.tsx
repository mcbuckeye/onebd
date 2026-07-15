import { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import api from '../lib/api';
import ContractClauseReviewPanel from '../components/ContractClauseReviewPanel';
import AdminApiAccessPanel from '../components/AdminApiAccessPanel';
import AdminOperationsPanel from '../components/AdminOperationsPanel';
import { Activity, Users, Plus, Edit2, Trash2, Shield, FileText, ClipboardCheck, KeyRound } from 'lucide-react';

interface User {
  id: number;
  email: string;
  name: string;
  role: string;
}

interface AuditLogEntry {
  id: number;
  user_id: number | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  ip_address: string | null;
  metadata: any;
  created_at: string;
  user_email: string | null;
}

interface UserFormData {
  email: string;
  password: string;
  name: string;
  role: string;
}

export default function AdminPage() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState<'users' | 'access' | 'operations' | 'audit' | 'clauses'>('users');
  const [users, setUsers] = useState<User[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditOffset, setAuditOffset] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [formData, setFormData] = useState<UserFormData>({
    email: '',
    password: '',
    name: '',
    role: 'analyst',
  });
  const [error, setError] = useState('');

  useEffect(() => {
    if (activeTab === 'users') {
      loadUsers();
    } else if (activeTab === 'audit') {
      loadAuditLogs();
    }
  }, [activeTab]);

  const loadUsers = async () => {
    setIsLoading(true);
    try {
      const resp = await api.get('/admin/users');
      setUsers(resp.data);
    } catch (err: any) {
      console.error('Failed to load users:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const loadAuditLogs = async () => {
    setIsLoading(true);
    try {
      const resp = await api.get(`/admin/audit-log?limit=50&offset=${auditOffset}`);
      setAuditLogs(resp.data.logs);
      setAuditTotal(resp.data.total);
    } catch (err: any) {
      console.error('Failed to load audit logs:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'audit') loadAuditLogs();
  }, [auditOffset]);

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    try {
      await api.post('/admin/users', formData);
      setShowModal(false);
      resetForm();
      loadUsers();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create user');
    }
  };

  const handleUpdateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!editingUser) return;

    try {
      await api.put(`/admin/users/${editingUser.id}`, {
        name: formData.name,
        role: formData.role,
      });
      setShowModal(false);
      resetForm();
      setEditingUser(null);
      loadUsers();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to update user');
    }
  };

  const handleDeleteUser = async (userId: number) => {
    if (!confirm('Disable this user account? They will no longer be able to sign in.')) return;

    try {
      await api.delete(`/admin/users/${userId}`);
      loadUsers();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to delete user');
    }
  };

  const openCreateModal = () => {
    setEditingUser(null);
    resetForm();
    setShowModal(true);
  };

  const openEditModal = (user: User) => {
    setEditingUser(user);
    setFormData({
      email: user.email,
      password: '',
      name: user.name,
      role: user.role,
    });
    setShowModal(true);
  };

  const resetForm = () => {
    setFormData({
      email: '',
      password: '',
      name: '',
      role: 'analyst',
    });
    setError('');
  };

  if (user?.role !== 'admin') {
    return (
      <div className="max-w-6xl mx-auto px-6 py-8">
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-6 text-center">
          <Shield className="w-12 h-12 text-red-500 mx-auto mb-4" />
          <h2 className="text-xl font-bold text-red-400 mb-2">Access Denied</h2>
          <p className="text-slate-400">This page is only accessible to administrators.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-3">
            <Users className="w-8 h-8 text-blue-500" />
            Admin Panel
          </h1>
          <p className="text-slate-400 text-sm mt-1">Manage users, colleague access, audits, and governed extraction review</p>
        </div>
        {activeTab === 'users' && (
          <button
            onClick={openCreateModal}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg flex items-center gap-2 transition-colors"
          >
            <Plus className="w-4 h-4" />
            Create User
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-6 border-b border-slate-800">
        <button
          onClick={() => setActiveTab('users')}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === 'users'
              ? 'text-blue-400 border-b-2 border-blue-400'
              : 'text-slate-400 hover:text-slate-300'
          }`}
        >
          <Users className="w-4 h-4 inline mr-2" />
          Users
        </button>
        <button
          onClick={() => setActiveTab('access')}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === 'access'
              ? 'text-blue-400 border-b-2 border-blue-400'
              : 'text-slate-400 hover:text-slate-300'
          }`}
        >
          <KeyRound className="w-4 h-4 inline mr-2" />
          API Access
        </button>
        <button
          onClick={() => setActiveTab('operations')}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === 'operations'
              ? 'text-blue-400 border-b-2 border-blue-400'
              : 'text-slate-400 hover:text-slate-300'
          }`}
        >
          <Activity className="w-4 h-4 inline mr-2" />
          Operations
        </button>
        <button
          onClick={() => setActiveTab('audit')}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === 'audit'
              ? 'text-blue-400 border-b-2 border-blue-400'
              : 'text-slate-400 hover:text-slate-300'
          }`}
        >
          <FileText className="w-4 h-4 inline mr-2" />
          Audit Log
        </button>
        <button
          onClick={() => setActiveTab('clauses')}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === 'clauses'
              ? 'text-blue-400 border-b-2 border-blue-400'
              : 'text-slate-400 hover:text-slate-300'
          }`}
        >
          <ClipboardCheck className="w-4 h-4 inline mr-2" />
          Clause Review
        </button>
      </div>

      {/* Users Table */}
      {activeTab === 'users' && (
        <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
        <table className="w-full">
          <thead className="bg-slate-800/50">
            <tr>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Name</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Email</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Role</th>
              <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {isLoading ? (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-slate-500">
                  Loading users...
                </td>
              </tr>
            ) : users.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-slate-500">
                  No users found
                </td>
              </tr>
            ) : (
              users.map((u) => (
                <tr key={u.id} className="hover:bg-slate-800/30">
                  <td className="px-4 py-3 text-slate-200">{u.name}</td>
                  <td className="px-4 py-3 text-slate-400 text-sm">{u.email}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                        u.role === 'admin'
                          ? 'bg-purple-500/20 text-purple-400'
                          : 'bg-slate-700 text-slate-300'
                      }`}
                    >
                      {u.role}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => openEditModal(u)}
                      className="inline-flex items-center gap-1 px-2 py-1 text-blue-400 hover:text-blue-300 text-sm mr-2"
                    >
                      <Edit2 className="w-3.5 h-3.5" />
                      Edit
                    </button>
                    <button
                      onClick={() => handleDeleteUser(u.id)}
                      className="inline-flex items-center gap-1 px-2 py-1 text-red-400 hover:text-red-300 text-sm"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      Disable
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      )}

      {activeTab === 'access' && <AdminApiAccessPanel />}

      {activeTab === 'operations' && <AdminOperationsPanel />}

      {/* Audit Log Table */}
      {activeTab === 'audit' && (
        <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-slate-800/50">
                <tr>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Time (local)</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">User</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Action</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">IP Address</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {isLoading ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-slate-500">
                      Loading audit logs...
                    </td>
                  </tr>
                ) : auditLogs.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-slate-500">
                      No audit logs found
                    </td>
                  </tr>
                ) : (
                  auditLogs.map((log) => (
                    <tr key={log.id} className="hover:bg-slate-800/30">
                      <td className="px-4 py-3 text-slate-400 text-sm">
                        {new Date(log.created_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-slate-200 text-sm">
                        {log.user_email || (log.user_id ? `User #${log.user_id}` : 'System')}
                      </td>
                      <td className="px-4 py-3">
                        <span className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-blue-500/20 text-blue-400">
                          {log.action}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-400 text-sm font-mono">
                        {log.ip_address || '-'}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          {auditTotal > 50 && (
            <div className="flex items-center justify-between border-t border-slate-800 px-4 py-3 text-xs text-slate-500">
              <span>
                Showing {auditOffset + 1}–{Math.min(auditOffset + 50, auditTotal)} of {auditTotal.toLocaleString()}
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={auditOffset === 0 || isLoading}
                  onClick={() => setAuditOffset(Math.max(0, auditOffset - 50))}
                  className="rounded border border-slate-700 px-3 py-1.5 disabled:opacity-40"
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={auditOffset + 50 >= auditTotal || isLoading}
                  onClick={() => setAuditOffset(auditOffset + 50)}
                  className="rounded border border-slate-700 px-3 py-1.5 disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === 'clauses' && <ContractClauseReviewPanel />}

      {/* Create/Edit User Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 w-full max-w-md">
            <h2 className="text-xl font-bold text-slate-100 mb-4">
              {editingUser ? 'Edit User' : 'Create New User'}
            </h2>

            <form onSubmit={editingUser ? handleUpdateUser : handleCreateUser}>
              {error && (
                <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">
                  {error}
                </div>
              )}

              <div className="mb-4">
                <label className="block text-sm text-slate-400 mb-1.5">Name</label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  required
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 text-sm focus:outline-none focus:border-blue-500"
                />
              </div>

              {!editingUser && (
                <>
                  <div className="mb-4">
                    <label className="block text-sm text-slate-400 mb-1.5">Email</label>
                    <input
                      type="email"
                      value={formData.email}
                      onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                      required
                      className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 text-sm focus:outline-none focus:border-blue-500"
                    />
                  </div>

                  <div className="mb-4">
                    <label className="block text-sm text-slate-400 mb-1.5">Password</label>
                    <input
                      type="password"
                      value={formData.password}
                      onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                      required
                      minLength={8}
                      className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 text-sm focus:outline-none focus:border-blue-500"
                    />
                  </div>
                </>
              )}

              <div className="mb-6">
                <label className="block text-sm text-slate-400 mb-1.5">Role</label>
                <select
                  value={formData.role}
                  onChange={(e) => setFormData({ ...formData, role: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 text-sm focus:outline-none focus:border-blue-500"
                >
                  <option value="analyst">Analyst</option>
                  <option value="admin">Admin</option>
                </select>
              </div>

              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => {
                    setShowModal(false);
                    setEditingUser(null);
                    resetForm();
                  }}
                  className="flex-1 px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors"
                >
                  {editingUser ? 'Update' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
