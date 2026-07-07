import React from 'react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-96 gap-3">
          <div className="text-lg">⚠️</div>
          <div className="text-sm" style={{ color: 'var(--text-muted)' }}>页面渲染出错</div>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="px-3 py-1.5 rounded-lg border text-sm"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
          >
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
