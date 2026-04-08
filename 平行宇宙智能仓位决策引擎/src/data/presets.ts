import { Asset } from '../services/SolverService';

export const PRESET_UNIVERSES: Record<string, Asset[]> = {
  'high-dividend': [
    { id: 'hd1', name: '煤炭能源', type: 'stock', style: 'high-dividend', currentPrice: 10.0, targetPrice: 11.2, certainty: 0.9, risk: 15 },
    { id: 'hd2', name: '国有大行', type: 'stock', style: 'high-dividend', currentPrice: 5.0, targetPrice: 5.5, certainty: 0.95, risk: 10 },
    { id: 'hd3', name: '高速公路', type: 'stock', style: 'high-dividend', currentPrice: 8.0, targetPrice: 8.64, certainty: 0.98, risk: 5 },
    { id: 'hd4', name: '通信巨头', type: 'stock', style: 'high-dividend', currentPrice: 20.0, targetPrice: 21.8, certainty: 0.85, risk: 12 },
    { id: 'hd5', name: '电力公用', type: 'stock', style: 'high-dividend', currentPrice: 6.5, targetPrice: 6.95, certainty: 0.9, risk: 8 },
  ],
  'white-horse': [
    { id: 'wh1', name: '高端白酒', type: 'stock', style: 'white-horse', currentPrice: 150.0, targetPrice: 172.5, certainty: 0.8, risk: 25 },
    { id: 'wh2', name: '互联网巨头', type: 'stock', style: 'white-horse', currentPrice: 80.0, targetPrice: 94.4, certainty: 0.75, risk: 30 },
    { id: 'wh3', name: '医药龙头', type: 'stock', style: 'white-horse', currentPrice: 45.0, targetPrice: 51.3, certainty: 0.85, risk: 20 },
    { id: 'wh4', name: '白色家电', type: 'stock', style: 'white-horse', currentPrice: 30.0, targetPrice: 33.3, certainty: 0.9, risk: 15 },
    { id: 'wh5', name: '动力电池', type: 'stock', style: 'white-horse', currentPrice: 120.0, targetPrice: 146.4, certainty: 0.6, risk: 40 },
  ],
  'growth': [
    { id: 'gr1', name: 'AI算力芯片', type: 'stock', style: 'growth', currentPrice: 50.0, targetPrice: 65.0, certainty: 0.4, risk: 60 },
    { id: 'gr2', name: '商业航天', type: 'stock', style: 'growth', currentPrice: 15.0, targetPrice: 20.25, certainty: 0.3, risk: 70 },
    { id: 'gr3', name: '创新药', type: 'stock', style: 'growth', currentPrice: 25.0, targetPrice: 31.25, certainty: 0.5, risk: 50 },
    { id: 'gr4', name: '云软件', type: 'stock', style: 'growth', currentPrice: 40.0, targetPrice: 48.0, certainty: 0.6, risk: 40 },
    { id: 'gr5', name: '人形机器人', type: 'stock', style: 'growth', currentPrice: 35.0, targetPrice: 44.8, certainty: 0.45, risk: 55 },
  ]
};
