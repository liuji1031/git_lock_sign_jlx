import * as React from 'react';

interface INotificationProps {
  message: string;
  type: 'success' | 'error' | 'info';
  onDismiss: () => void;
}

export const Notification: React.FC<INotificationProps> = ({ message, type, onDismiss }) => {
  const [visible, setVisible] = React.useState(true);

  React.useEffect(() => {
    const timer = setTimeout(() => {
      handleDismiss();
    }, 5000); // Auto-dismiss after 5 seconds

    return () => clearTimeout(timer);
  }, []);

  const handleDismiss = () => {
    setVisible(false);
    onDismiss();
  };

  if (!visible) {
    return null;
  }

  return (
    <div className={`git-lock-sign-notification ${type}`}>
      <p>{message}</p>
      <button onClick={handleDismiss} className="dismiss-button">
        &times;
      </button>
    </div>
  );
};
