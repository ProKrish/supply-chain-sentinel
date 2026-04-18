import { useAuth0 } from '@auth0/auth0-react';

export default function LoginPage() {
  const { loginWithRedirect, isLoading } = useAuth0();

  return (
    <div style={{
      minHeight: '100vh',
      backgroundColor: '#0f172a',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'system-ui, sans-serif'
    }}>
      {/* Icon */}
      <svg width="80" height="80" viewBox="0 0 80 80" fill="none"
        style={{ marginBottom: '32px' }}>
        <circle cx="40" cy="40" r="38" stroke="#06b6d4" strokeWidth="2"
          fill="none" opacity="0.3" />
        <circle cx="40" cy="20" r="6" fill="#06b6d4" />
        <circle cx="20" cy="55" r="6" fill="#06b6d4" />
        <circle cx="60" cy="55" r="6" fill="#06b6d4" />
        <line x1="40" y1="26" x2="20" y2="49"
          stroke="#06b6d4" strokeWidth="2" opacity="0.7" />
        <line x1="40" y1="26" x2="60" y2="49"
          stroke="#06b6d4" strokeWidth="2" opacity="0.7" />
        <line x1="26" y1="55" x2="54" y2="55"
          stroke="#06b6d4" strokeWidth="2" opacity="0.7" />
      </svg>

      {/* Title */}
      <h1 style={{
        color: 'white',
        fontSize: '36px',
        fontWeight: '700',
        margin: '0 0 12px 0',
        letterSpacing: '-0.5px'
      }}>
        Supply Chain Sentinel
      </h1>

      {/* Subtitle */}
      <p style={{
        color: '#94a3b8',
        fontSize: '16px',
        margin: '0 0 40px 0',
        textAlign: 'center',
        maxWidth: '400px'
      }}>
        Preemptive Disruption Detection &amp; AI-Powered Rerouting
      </p>

      {/* Login Button */}
      <button
        onClick={() => loginWithRedirect()}
        disabled={isLoading}
        style={{
          backgroundColor: '#06b6d4',
          color: 'white',
          padding: '14px 40px',
          borderRadius: '8px',
          border: 'none',
          fontSize: '16px',
          fontWeight: '600',
          cursor: isLoading ? 'not-allowed' : 'pointer',
          opacity: isLoading ? 0.7 : 1,
          transition: 'opacity 0.2s'
        }}
      >
        {isLoading ? 'Loading...' : 'Sign In to Dashboard'}
      </button>

      {/* Footer */}
      <p style={{
        color: '#475569',
        fontSize: '13px',
        position: 'absolute',
        bottom: '24px'
      }}>
        © 2026 Supply Chain Sentinel
      </p>
    </div>
  );
}