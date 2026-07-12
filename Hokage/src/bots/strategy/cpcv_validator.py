import logging
from typing import List, Tuple
from itertools import combinations
import numpy as np

logger = logging.getLogger("Hokage.CPCVValidator")

class CPCVValidator:
    """
    Combinatorial Purged Cross-Validation (CPCV) for AI generated setups.
    Prevents data leakage by strictly purging training data overlap.
    """
    def __init__(self, purge_bars: int = 5, embargo_bars: int = 2):
        self.purge_bars = purge_bars
        self.embargo_bars = embargo_bars

    def split(self, total_bars: int, k_folds: int = 5, num_test_folds: int = 2) -> List[Tuple[np.ndarray, np.ndarray]]:
        """
        Generate train/test indices using CPCV algorithm.
        Splits data into `k_folds` paths, combining `num_test_folds` for testing.
        Applies purging and embargoing between train and test sets.
        """
        if total_bars < k_folds:
            return []
            
        indices = np.arange(total_bars)
        fold_size = total_bars // k_folds
        folds = []
        for i in range(k_folds):
            start = i * fold_size
            end = (i + 1) * fold_size if i < k_folds - 1 else total_bars
            folds.append(indices[start:end])
            
        splits = []
        # Generate all combinations of test folds
        for test_fold_indices in combinations(range(k_folds), num_test_folds):
            test_idx = np.concatenate([folds[i] for i in test_fold_indices])
            train_idx = []
            
            for i in range(k_folds):
                if i in test_fold_indices:
                    continue
                    
                # Apply Purge and Embargo
                # If a test fold precedes this train fold, apply embargo
                # If a test fold succeeds this train fold, apply purge
                current_train = folds[i].copy()
                
                # Check relation to all test folds
                for t_idx in test_fold_indices:
                    if t_idx < i:
                        # Test fold comes before train fold -> Embargo
                        embargo_cutoff = folds[t_idx][-1] + self.embargo_bars
                        current_train = current_train[current_train > embargo_cutoff]
                    elif t_idx > i:
                        # Test fold comes after train fold -> Purge
                        purge_cutoff = folds[t_idx][0] - self.purge_bars
                        current_train = current_train[current_train < purge_cutoff]
                
                if len(current_train) > 0:
                    train_idx.append(current_train)
                    
            if train_idx:
                train_idx = np.concatenate(train_idx)
                splits.append((train_idx, test_idx))
                
        return splits

    def validate_strategy(self, strategy_func, price_data: np.ndarray) -> bool:
        """
        Mock validation. Uses CPCV to determine if strategy is robust.
        """
        splits = self.split(len(price_data))
        if not splits:
            return False
            
        passed_folds = 0
        for train_idx, test_idx in splits:
            # Simulate training/testing
            # In a real scenario, strategy_func trains on price_data[train_idx]
            # and is evaluated on price_data[test_idx].
            # Mock success rate 60%
            if np.random.random() > 0.4:
                passed_folds += 1
                
        # Must pass at least 70% of CPCV paths
        return (passed_folds / len(splits)) >= 0.7
