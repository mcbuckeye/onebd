import { createBrowserRouter } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import { ErrorBoundary } from './components/ErrorBoundary';
import MainLayout from './layouts/MainLayout';
import PageLoader from './components/PageLoader';

// Lazy load all pages for code splitting
const LoginPage = lazy(() => import('./pages/LoginPage'));
const ForgotPasswordPage = lazy(() => import('./pages/ForgotPasswordPage'));
const ResetPasswordPage = lazy(() => import('./pages/ResetPasswordPage'));
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const SearchPage = lazy(() => import('./pages/SearchPage'));
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'));
const CompetitorsPage = lazy(() => import('./pages/CompetitorsPage'));
const GraphPage = lazy(() => import('./pages/GraphPage'));
const FilingsPage = lazy(() => import('./pages/FilingsPage'));
const ContractsPage = lazy(() => import('./pages/ContractsPage'));
const MyDealsPage = lazy(() => import('./pages/MyDealsPage'));
const ChatPage = lazy(() => import('./pages/ChatPage'));
const CompanyProfilePage = lazy(() => import('./pages/CompanyProfilePage'));
const DrugProfilePage = lazy(() => import('./pages/DrugProfilePage'));
const CompBuilderPage = lazy(() => import('./pages/CompBuilderPage'));
const DDPage = lazy(() => import('./pages/DDPage'));
const TerritoryPage = lazy(() => import('./pages/TerritoryPage'));
const BriefingPage = lazy(() => import('./pages/BriefingPage'));
const GuidePage = lazy(() => import('./pages/GuidePage'));
const AdminPage = lazy(() => import('./pages/AdminPage'));

// Wrapper component to add ErrorBoundary + Suspense to each route
const withErrorBoundary = (Component: React.LazyExoticComponent<React.ComponentType>) => (
  <ErrorBoundary>
    <Suspense fallback={<PageLoader />}>
      <Component />
    </Suspense>
  </ErrorBoundary>
);

export const router = createBrowserRouter([
  {
    path: '/login',
    element: withErrorBoundary(LoginPage),
  },
  {
    path: '/forgot-password',
    element: withErrorBoundary(ForgotPasswordPage),
  },
  {
    path: '/reset-password',
    element: withErrorBoundary(ResetPasswordPage),
  },
  {
    path: '/',
    element: <MainLayout />,
    children: [
      { index: true, element: withErrorBoundary(DashboardPage) },
      { path: 'search', element: withErrorBoundary(SearchPage) },
      { path: 'analytics', element: withErrorBoundary(AnalyticsPage) },
      { path: 'competitors', element: withErrorBoundary(CompetitorsPage) },
      { path: 'graph', element: withErrorBoundary(GraphPage) },
      { path: 'filings', element: withErrorBoundary(FilingsPage) },
      { path: 'contracts', element: withErrorBoundary(ContractsPage) },
      { path: 'my-deals', element: withErrorBoundary(MyDealsPage) },
      { path: 'comps', element: withErrorBoundary(CompBuilderPage) },
      { path: 'dd', element: withErrorBoundary(DDPage) },
      { path: 'territory', element: withErrorBoundary(TerritoryPage) },
      { path: 'briefings', element: withErrorBoundary(BriefingPage) },
      { path: 'chat', element: withErrorBoundary(ChatPage) },
      { path: 'company/:companyId', element: withErrorBoundary(CompanyProfilePage) },
      { path: 'drug/:drugId', element: withErrorBoundary(DrugProfilePage) },
      { path: 'guide', element: withErrorBoundary(GuidePage) },
      { path: 'admin', element: withErrorBoundary(AdminPage) },
    ],
  },
]);
