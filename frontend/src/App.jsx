import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';
import LoginPage from './pages/LoginPage';
import Dashboard from './pages/Dashboard';
import Callback from './pages/Callback';
import Analytics from './pages/Analytics';

const ProtectedRoute = ({ children }) => {
  const { isAuthenticated, isLoading } = useAuth0();

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#0f172a] flex flex-col items-center justify-center">
        <div className="w-12 h-12 border-4 border-t-[#06b6d4] border-r-[#06b6d4] border-b-transparent border-l-transparent rounded-full animate-spin"></div>
        <p className="mt-4 text-white text-lg">Loading...</p>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return children;
};

function App() {
  const { isAuthenticated } = useAuth0();

  return (
    <Routes>
      <Route 
        path="/" 
        element={isAuthenticated ? <Navigate to="/dashboard" replace /> : <LoginPage />} 
      />
      <Route 
        path="/dashboard" 
        element={
          <ProtectedRoute>
            <Dashboard />
          </ProtectedRoute>
        } 
      />
      <Route
        path="/analytics"
        element={
          <ProtectedRoute>
            <Analytics />
          </ProtectedRoute>
        }
      />
      <Route path="/callback" element={<Callback />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
