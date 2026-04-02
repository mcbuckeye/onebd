import { useState, useEffect } from 'react';
import { Settings as SettingsIcon, Mail, Bell, Check, X, Loader2 } from 'lucide-react';
import api from '../lib/api';
import { useAuth } from '../contexts/AuthContext';

interface DigestSettings {
  enabled: boolean;
  frequency: string;
  therapy_areas: string[];
  company_ids: number[];
  email: string | null;
}

interface Company {
  id: number;
  name: string;
  company_type?: string;
  ticker?: string;
}

export default function SettingsPage() {
  const { user } = useAuth();
  const [settings, setSettings] = useState<DigestSettings>({
    enabled: false,
    frequency: 'weekly',
    therapy_areas: [],
    company_ids: [],
    email: user?.email || null,
  });
  
  const [therapyAreaOptions, setTherapyAreaOptions] = useState<string[]>([]);
  const [companySearch, setCompanySearch] = useState('');
  const [companyResults, setCompanyResults] = useState<Company[]>([]);
  const [selectedCompanies, setSelectedCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [successMessage, setSuccessMessage] = useState('');

  // Load settings and therapy areas on mount
  useEffect(() => {
    Promise.all([
      api.get('/settings/digest'),
      api.get('/search/filters'),
    ])
      .then(([settingsRes, filtersRes]) => {
        const loadedSettings = settingsRes.data;
        setSettings({
          ...loadedSettings,
          email: loadedSettings.email || user?.email || null,
        });
        setTherapyAreaOptions(filtersRes.data.therapy_areas || []);
        
        // Load company names for selected company_ids
        if (loadedSettings.company_ids && loadedSettings.company_ids.length > 0) {
          loadSelectedCompanies(loadedSettings.company_ids);
        }
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [user?.email]);

  const loadSelectedCompanies = async (companyIds: number[]) => {
    try {
      // Fetch company details for each ID
      const companyPromises = companyIds.map(id =>
        api.get(`/entities/company/${id}`).catch(() => null)
      );
      const results = await Promise.all(companyPromises);
      const companies = results
        .filter(res => res !== null)
        .map(res => ({
          id: res.data.id,
          name: res.data.name,
          company_type: res.data.company_type,
          ticker: res.data.ticker,
        }));
      setSelectedCompanies(companies);
    } catch (error) {
      console.error('Failed to load selected companies:', error);
    }
  };

  // Company autocomplete
  useEffect(() => {
    if (companySearch.length < 2) {
      setCompanyResults([]);
      return;
    }

    const timer = setTimeout(() => {
      api.get('/search/autocomplete/companies', {
        params: { q: companySearch, limit: 10 },
      })
        .then(res => setCompanyResults(res.data))
        .catch(console.error);
    }, 300);

    return () => clearTimeout(timer);
  }, [companySearch]);

  const addCompany = (company: Company) => {
    if (!selectedCompanies.find(c => c.id === company.id)) {
      setSelectedCompanies([...selectedCompanies, company]);
      setSettings({
        ...settings,
        company_ids: [...settings.company_ids, company.id],
      });
    }
    setCompanySearch('');
    setCompanyResults([]);
  };

  const removeCompany = (companyId: number) => {
    setSelectedCompanies(selectedCompanies.filter(c => c.id !== companyId));
    setSettings({
      ...settings,
      company_ids: settings.company_ids.filter(id => id !== companyId),
    });
  };

  const toggleTherapyArea = (area: string) => {
    const newAreas = settings.therapy_areas.includes(area)
      ? settings.therapy_areas.filter(a => a !== area)
      : [...settings.therapy_areas, area];
    setSettings({ ...settings, therapy_areas: newAreas });
  };

  const handleSave = async () => {
    setSaving(true);
    setSuccessMessage('');
    try {
      await api.put('/settings/digest', settings);
      setSuccessMessage('Settings saved successfully');
      setTimeout(() => setSuccessMessage(''), 3000);
    } catch (error) {
      console.error('Failed to save settings:', error);
      alert('Failed to save settings. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-8 h-8 text-slate-400 animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-6">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <SettingsIcon className="w-7 h-7 text-slate-400" />
        <h1 className="text-2xl font-bold text-slate-100">Settings</h1>
      </div>

      {/* Email Digest Section */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 mb-6">
        <div className="flex items-center gap-3 mb-6">
          <Mail className="w-6 h-6 text-blue-400" />
          <h2 className="text-lg font-semibold text-slate-100">Email Digest</h2>
        </div>

        {/* Enable/Disable Toggle */}
        <div className="flex items-center justify-between mb-6 pb-6 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <Bell className="w-5 h-5 text-slate-400" />
            <div>
              <div className="font-medium text-slate-200">Enable Email Digest</div>
              <div className="text-sm text-slate-500">Receive periodic updates about tracked deals</div>
            </div>
          </div>
          <button
            onClick={() => setSettings({ ...settings, enabled: !settings.enabled })}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              settings.enabled ? 'bg-blue-600' : 'bg-slate-700'
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                settings.enabled ? 'translate-x-6' : 'translate-x-1'
              }`}
            />
          </button>
        </div>

        {/* Frequency */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-slate-300 mb-2">Frequency</label>
          <select
            value={settings.frequency}
            onChange={(e) => setSettings({ ...settings, frequency: e.target.value })}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 focus:outline-none focus:border-blue-500"
            disabled={!settings.enabled}
          >
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="off">Off</option>
          </select>
        </div>

        {/* Email Address */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-slate-300 mb-2">Email Address</label>
          <input
            type="email"
            value={settings.email || ''}
            onChange={(e) => setSettings({ ...settings, email: e.target.value })}
            placeholder={user?.email || 'your@email.com'}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
            disabled={!settings.enabled}
          />
          <p className="text-xs text-slate-500 mt-1">Defaults to your login email if left blank</p>
        </div>

        {/* Therapy Areas */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-slate-300 mb-2">Tracked Therapy Areas</label>
          <div className="grid grid-cols-2 gap-2 max-h-48 overflow-y-auto p-3 bg-slate-800/50 border border-slate-700 rounded-lg">
            {therapyAreaOptions.length === 0 ? (
              <div className="col-span-2 text-sm text-slate-500 text-center py-4">No therapy areas available</div>
            ) : (
              therapyAreaOptions.map(area => (
                <label key={area} className="flex items-center gap-2 text-sm text-slate-300 hover:bg-slate-700/50 p-2 rounded cursor-pointer">
                  <input
                    type="checkbox"
                    checked={settings.therapy_areas.includes(area)}
                    onChange={() => toggleTherapyArea(area)}
                    disabled={!settings.enabled}
                    className="rounded border-slate-600 text-blue-600 focus:ring-blue-500 focus:ring-offset-slate-800"
                  />
                  <span>{area}</span>
                </label>
              ))
            )}
          </div>
        </div>

        {/* Company Search */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-slate-300 mb-2">Tracked Companies</label>
          <div className="relative">
            <input
              type="text"
              value={companySearch}
              onChange={(e) => setCompanySearch(e.target.value)}
              placeholder="Search companies..."
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
              disabled={!settings.enabled}
            />
            {companyResults.length > 0 && (
              <div className="absolute z-10 w-full mt-1 bg-slate-800 border border-slate-700 rounded-lg shadow-lg max-h-60 overflow-y-auto">
                {companyResults.map(company => (
                  <button
                    key={company.id}
                    onClick={() => addCompany(company)}
                    className="w-full px-3 py-2 text-left hover:bg-slate-700 flex items-center justify-between"
                  >
                    <div>
                      <div className="text-sm text-slate-200">{company.name}</div>
                      {company.ticker && (
                        <div className="text-xs text-slate-500">{company.ticker}</div>
                      )}
                    </div>
                    {company.company_type && (
                      <span className="text-xs text-slate-500">{company.company_type}</span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Selected Companies */}
          <div className="flex flex-wrap gap-2 mt-3">
            {selectedCompanies.map(company => (
              <div
                key={company.id}
                className="flex items-center gap-2 px-3 py-1.5 bg-blue-600/20 text-blue-400 border border-blue-500/30 rounded-full text-sm"
              >
                <span>{company.name}</span>
                <button
                  onClick={() => removeCompany(company.id)}
                  className="hover:bg-blue-500/20 rounded-full p-0.5"
                  disabled={!settings.enabled}
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Save Button */}
        <div className="flex items-center gap-3 pt-4 border-t border-slate-800">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Saving...</span>
              </>
            ) : (
              <>
                <Check className="w-4 h-4" />
                <span>Save Settings</span>
              </>
            )}
          </button>

          {successMessage && (
            <div className="flex items-center gap-2 text-green-400 text-sm">
              <Check className="w-4 h-4" />
              <span>{successMessage}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
