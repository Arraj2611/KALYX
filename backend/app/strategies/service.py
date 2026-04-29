"""
Strategy service for managing strategies.
"""
import logging
import json
import importlib
import inspect
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.data import models
from app.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class StrategyService:
    """Service for managing trading strategies."""
    
    def __init__(self, db: Session):
        self.db = db
        self._strategy_cache: Dict[int, BaseStrategy] = {}
    
    def list_strategies(self) -> List[Dict]:
        """List all strategies."""
        strategies = self.db.query(models.Strategy).all()
        return [self._strategy_to_dict(s) for s in strategies]
    
    def get_strategy(self, strategy_id: int) -> Optional[Dict]:
        """Get strategy by ID."""
        strategy = self.db.query(models.Strategy).filter(
            models.Strategy.id == strategy_id
        ).first()
        if not strategy:
            return None
        return self._strategy_to_dict(strategy)
    
    def create_strategy(
        self,
        name: str,
        description: Optional[str],
        strategy_type: str,
        config: Dict[str, Any],
        code: Optional[str] = None
    ) -> Dict:
        """Create a new strategy."""
        strategy = models.Strategy(
            name=name,
            description=description,
            strategy_type=strategy_type,
            config=config,
            code=code,
            is_active=False
        )
        self.db.add(strategy)
        self.db.commit()
        self.db.refresh(strategy)
        
        logger.info(f"Created strategy: {name} (ID: {strategy.id})")
        return self._strategy_to_dict(strategy)
    
    def update_strategy(
        self,
        strategy_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        code: Optional[str] = None
    ) -> Dict:
        """Update strategy."""
        strategy = self.db.query(models.Strategy).filter(
            models.Strategy.id == strategy_id
        ).first()
        
        if not strategy:
            raise ValueError(f"Strategy {strategy_id} not found")
        
        if name:
            strategy.name = name
        if description:
            strategy.description = description
        if config:
            strategy.config = config
        if code:
            strategy.code = code
        
        self.db.commit()
        self.db.refresh(strategy)
        
        # Clear cache
        if strategy_id in self._strategy_cache:
            del self._strategy_cache[strategy_id]
        
        logger.info(f"Updated strategy: {strategy_id}")
        return self._strategy_to_dict(strategy)
    
    def delete_strategy(self, strategy_id: int):
        """Delete strategy."""
        strategy = self.db.query(models.Strategy).filter(
            models.Strategy.id == strategy_id
        ).first()
        
        if not strategy:
            raise ValueError(f"Strategy {strategy_id} not found")
        
        if strategy.is_active:
            raise ValueError("Cannot delete active strategy. Deactivate first.")
        
        self.db.delete(strategy)
        self.db.commit()
        
        # Clear cache
        if strategy_id in self._strategy_cache:
            del self._strategy_cache[strategy_id]
        
        logger.info(f"Deleted strategy: {strategy_id}")
    
    def activate_strategy(self, strategy_id: int):
        """Activate a strategy."""
        strategy = self.db.query(models.Strategy).filter(
            models.Strategy.id == strategy_id
        ).first()
        
        if not strategy:
            raise ValueError(f"Strategy {strategy_id} not found")
        
        strategy.is_active = True
        self.db.commit()
        
        # Load strategy instance
        self._load_strategy_instance(strategy_id)
        
        logger.info(f"Activated strategy: {strategy_id}")
    
    def deactivate_strategy(self, strategy_id: int):
        """Deactivate a strategy."""
        strategy = self.db.query(models.Strategy).filter(
            models.Strategy.id == strategy_id
        ).first()
        
        if not strategy:
            raise ValueError(f"Strategy {strategy_id} not found")
        
        strategy.is_active = False
        self.db.commit()
        
        # Clear cache
        if strategy_id in self._strategy_cache:
            strategy_instance = self._strategy_cache[strategy_id]
            strategy_instance.on_deactivate()
            del self._strategy_cache[strategy_id]
        
        logger.info(f"Deactivated strategy: {strategy_id}")
    
    def export_strategy(self, strategy_id: int) -> Dict[str, Any]:
        """Export strategy as JSON."""
        strategy = self.db.query(models.Strategy).filter(
            models.Strategy.id == strategy_id
        ).first()
        
        if not strategy:
            raise ValueError(f"Strategy {strategy_id} not found")
        
        return {
            "name": strategy.name,
            "description": strategy.description,
            "strategy_type": strategy.strategy_type,
            "config": strategy.config,
            "code": strategy.code
        }
    
    def import_strategy(self, strategy_data: Dict[str, Any]) -> Dict:
        """Import strategy from JSON."""
        return self.create_strategy(
            name=strategy_data["name"],
            description=strategy_data.get("description"),
            strategy_type=strategy_data["strategy_type"],
            config=strategy_data["config"],
            code=strategy_data.get("code")
        )
    
    def get_strategy_instance(self, strategy_id: int) -> Optional[BaseStrategy]:
        """Get loaded strategy instance."""
        if strategy_id in self._strategy_cache:
            return self._strategy_cache[strategy_id]
        
        strategy = self.db.query(models.Strategy).filter(
            models.Strategy.id == strategy_id
        ).first()
        
        if not strategy or not strategy.is_active:
            return None
        
        return self._load_strategy_instance(strategy_id)
    
    def _load_strategy_instance(self, strategy_id: int) -> BaseStrategy:
        """Load strategy instance from database."""
        strategy = self.db.query(models.Strategy).filter(
            models.Strategy.id == strategy_id
        ).first()
        
        if not strategy:
            raise ValueError(f"Strategy {strategy_id} not found")
        
        # Try to load from code if available
        if strategy.code:
            try:
                # Dynamic code execution (in production, use safer method)
                exec_globals = {
                    "BaseStrategy": BaseStrategy,
                    "__builtins__": __builtins__
                }
                exec(strategy.code, exec_globals)
                
                # Find the strategy class
                for name, obj in exec_globals.items():
                    if (inspect.isclass(obj) and 
                        issubclass(obj, BaseStrategy) and 
                        obj != BaseStrategy):
                        strategy_class = obj
                        instance = strategy_class(strategy.config)
                        instance.on_activate()
                        self._strategy_cache[strategy_id] = instance
                        return instance
            except Exception as e:
                logger.error(f"Failed to load strategy code: {e}", exc_info=True)
        
        # Fallback to built-in strategies
        from app.strategies import builtin
        strategy_class = getattr(builtin, strategy.strategy_type, None)
        if strategy_class:
            instance = strategy_class(strategy.config)
            instance.on_activate()
            self._strategy_cache[strategy_id] = instance
            return instance
        
        raise ValueError(f"Could not load strategy: {strategy.strategy_type}")
    
    def _strategy_to_dict(self, strategy: models.Strategy) -> Dict:
        """Convert strategy model to dictionary."""
        return {
            "id": strategy.id,
            "name": strategy.name,
            "description": strategy.description,
            "strategy_type": strategy.strategy_type,
            "config": strategy.config,
            "is_active": strategy.is_active,
            "created_at": strategy.created_at.isoformat() if strategy.created_at else None,
            "updated_at": strategy.updated_at.isoformat() if strategy.updated_at else None
        }

