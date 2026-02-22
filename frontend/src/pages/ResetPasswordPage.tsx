import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { BarChart3, CheckCircle } from 'lucide-react';
import axios from 'axios';

export default function ResetPasswordPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');

  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!token) {
      setError('Invalid reset link. Please request a new password reset.');
    }
  }, [token]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    if (password.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }

    if (!token) {
      setError('Invalid reset link');
      return;
    }

    setIsLoading(true);

    try {
      await axios.post('/api/auth/reset-password', {
        token,
        new_password: password,
      });
      setSuccess(true);
      setTimeout(() => navigate('/login'), 3000);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to reset password');
    } finally {
      setIsLoading(false);
    }
  };

  if (success) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4">
        <div className="w-full max-w-sm">
          <div className="bg-slate-900 rounded-xl p-6 border border-slate-800 text-center">
            <CheckCircle className="w-16 h-16 text-green-500 mx-auto mb-4" />
            <h2 className="text-xl font-bold text-slate-100 mb-2">Password Reset Complete</h2>
            <p className="text-slate-400 text-sm mb-4">
              Your password has been successfully updated.
            </p>
            <p className="text-slate-500 text-xs">
              Redirecting to login...
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <BarChart3 className="w-12 h-12 text-blue-500 mx-auto mb-3" />
          <h1 className="text-2xl font-bold text-slate-100">Set New Password</h1>
          <p className="text-slate-500 text-sm mt-1">Enter your new password</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-slate-900 rounded-xl p-6 border border-slate-800">
          {error && (
            <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">
              {error}
            </div>
          )}

          <div className="mb-4">
            <label className="block text-sm text-slate-400 mb-1.5">New Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              disabled={!token}
              autoFocus
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 text-sm focus:outline-none focus:border-blue-500 disabled:opacity-50"
            />
          </div>

          <div className="mb-6">
            <label className="block text-sm text-slate-400 mb-1.5">Confirm Password</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={8}
              disabled={!token}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 text-sm focus:outline-none focus:border-blue-500 disabled:opacity-50"
            />
          </div>

          <button
            type="submit"
            disabled={isLoading || !token}
            className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors mb-4"
          >
            {isLoading ? 'Resetting...' : 'Reset Password'}
          </button>

          <Link
            to="/login"
            className="block text-center text-slate-400 hover:text-slate-300 transition-colors text-sm"
          >
            Back to login
          </Link>
        </form>
      </div>
    </div>
  );
}
