import { useState } from 'react';
import { Link } from 'react-router-dom';
import { BarChart3, ArrowLeft } from 'lucide-react';
import axios from 'axios';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      await axios.post('/api/auth/forgot-password', { email });
      setSubmitted(true);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to send reset email');
    } finally {
      setIsLoading(false);
    }
  };

  if (submitted) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4">
        <div className="w-full max-w-sm">
          <div className="text-center mb-8">
            <BarChart3 className="w-12 h-12 text-blue-500 mx-auto mb-3" />
            <h1 className="text-2xl font-bold text-slate-100">Check Your Email</h1>
          </div>

          <div className="bg-slate-900 rounded-xl p-6 border border-slate-800 text-center">
            <p className="text-slate-300 mb-6">
              If an account exists with <strong className="text-slate-100">{email}</strong>, 
              you will receive password reset instructions.
            </p>
            <p className="text-sm text-slate-500 mb-6">
              Please check your inbox and spam folder.
            </p>
            <Link
              to="/login"
              className="inline-flex items-center gap-2 text-blue-500 hover:text-blue-400 transition-colors text-sm"
            >
              <ArrowLeft className="w-4 h-4" />
              Back to login
            </Link>
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
          <h1 className="text-2xl font-bold text-slate-100">Reset Password</h1>
          <p className="text-slate-500 text-sm mt-1">Enter your email to receive reset instructions</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-slate-900 rounded-xl p-6 border border-slate-800">
          {error && (
            <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">
              {error}
            </div>
          )}

          <div className="mb-6">
            <label className="block text-sm text-slate-400 mb-1.5">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 text-sm focus:outline-none focus:border-blue-500"
            />
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors mb-4"
          >
            {isLoading ? 'Sending...' : 'Send Reset Link'}
          </button>

          <Link
            to="/login"
            className="flex items-center justify-center gap-2 text-slate-400 hover:text-slate-300 transition-colors text-sm"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to login
          </Link>
        </form>
      </div>
    </div>
  );
}
