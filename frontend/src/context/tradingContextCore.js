import { createContext, useContext } from 'react';

export const TradingContext = createContext(null);

export function useTrading() {
  const context = useContext(TradingContext);
  if (!context) throw new Error('useTrading must be used within TradingProvider');
  return context;
}
