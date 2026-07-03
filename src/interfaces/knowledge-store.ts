/**
 * Knowledge Store Manager interfaces.
 *
 * Responsibility: Persistent storage of user preferences and facts;
 * document lifecycle management.
 */

export interface KnowledgeStoreManager {
  /** Store a user preference or fact */
  storeItem(userId: string, item: KnowledgeItem): Promise<string>;
  /** Remove an item */
  removeItem(userId: string, itemId: string): Promise<void>;
  /** Get all stored items for user */
  getItems(userId: string): Promise<KnowledgeItem[]>;
  /** Count items */
  getItemCount(userId: string): Promise<number>;
}

export interface KnowledgeItem {
  id: string;
  type: 'preference' | 'fact' | 'document';
  content: string;
  createdAt: Date;
  metadata: Record<string, string>;
}
