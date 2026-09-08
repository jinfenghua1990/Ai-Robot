import React from 'react';

export default class CardSafetyBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error) {
    if (this.props.onError) this.props.onError(error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          className="rounded-lg border p-3 text-xs"
          style={{
            borderColor: 'rgba(239,68,68,0.3)',
            background: 'rgba(239,68,68,0.04)',
            color: '#ef4444',
          }}
        >
          ⚠️ 渲染失败
          <button
            onClick={() => this.setState({ hasError: false })}
            className="ml-2 underline"
            style={{ color: '#ef4444' }}
          >
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
